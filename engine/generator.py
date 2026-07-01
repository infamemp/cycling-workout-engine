"""
generator.py — End-to-end orchestration (Phase 1, deterministic core).

Flow: request -> (conflict checks) -> build mandatory structure ->
provisional main set -> assemble .md -> compute real TSS -> catalog.

================================ IMPORTANT ================================
The structure DECISIONS in this module (warmup ramp range, main-set reps/
durations, cooldown form) are PROVISIONAL PHASE-1 PLACEHOLDERS, present only
so the pipeline runs end-to-end and is testable. The Phase-2 Claude reasoning
layer will REPLACE these decisions with real, varied, catalog-aware,
physiology-grounded reasoning. The plumbing (structure assembly, TSS math,
rendering, validation, catalog) is the durable part.
==========================================================================
"""

from __future__ import annotations
import uuid
import random
from typing import Optional

from .models import GenerationRequest, GeneratedSession, Feasibility
from .zones import zone_by_name
from . import structure as struct
from . import assembler
from .catalog import Catalog, CatalogEntry


# Provisional default warmup/cooldown ramp ranges (Phase-1 only).
_WARMUP_RAMP = (45, 75)
_COOLDOWN_RAMP = (75, 45)


def generate_single(req: GenerationRequest, *,
                    catalog: Optional[Catalog] = None,
                    seed: Optional[int] = None,
                    progression_id: Optional[str] = None) -> GeneratedSession:
    """Generate one session end-to-end. Phase-1 provisional structure."""
    if req.mode not in ("power", "hr"):
        raise ValueError("mode must be 'power' or 'hr'")
    if not req.requested_zone:
        raise ValueError("Phase-1 generator requires an explicit requested_zone")

    rng = random.Random(seed)

    # Hard-constraint conflict detection (spec 16.3) — report, never force.
    struct.check_duration_vs_tss(
        req.target_tss, req.target_if, req.max_available_seconds
    )
    _caps = [x for x in (req.target_duration_seconds,
                         req.max_available_seconds) if x]
    struct.check_zone_feasibility(req.mode, req.requested_zone,
                                  req.target_tss, req.target_if,
                                  min(_caps) if _caps else None)

    zone = zone_by_name(req.mode, req.requested_zone)
    # For the placeholder we need concrete work %s; use the zone's interior.
    z_low = zone.low_pct
    z_high = zone.high_pct if zone.high_pct is not None else zone.low_pct + 10

    # --- Mandatory structure (durable), mode-dependent shape (spec 11) ---
    if req.mode == "power":
        warmup = struct.build_warmup(req.mode, *_WARMUP_RAMP)
        cooldown = struct.build_cooldown_ramp(req.mode, *_COOLDOWN_RAMP)
    else:  # hr — staircase warmup + single-block cooldown (spec 11.1/11.3)
        # [PHASE-1 PLACEHOLDER] staircase step count/%s are provisional; the
        # number of steps is NOT fixed (Phase 2 reasons it). Here we build a
        # simple ascending staircase toward the main-set zone.
        n_steps = rng.choice([4, 5, 6])           # provisional, not fixed
        start_pct = 50
        end_pct = max(start_pct + 1, min(z_low, 85))
        span = end_pct - start_pct
        stair: list[tuple[int, int, int]] = []
        for i in range(n_steps):
            lo = round(start_pct + span * i / n_steps)
            hi = round(start_pct + span * (i + 1) / n_steps)
            stair.append((lo, hi, 120))           # 2 min each (<=10 min total)
        # clip total to 10 min
        while sum(s[2] for s in stair) > struct.WARMUP_RAMP_MAX:
            stair.pop()
        warmup = struct.build_warmup_hr_staircase(stair)
        cooldown = struct.build_cooldown_hr_single(60, 70)

    # --- PROVISIONAL main set (Phase-1 placeholder) ---
    # Dumb fixed-ish shape, lightly seeded for variety in testing only.
    reps = rng.choice([3, 4, 5])
    work_each = rng.choice([300, 480, 600])  # 5/8/10 min
    recovery_each = rng.choice([120, 180])
    main_block = struct.provisional_main_set(
        mode=req.mode, zone_low=z_low, zone_high=z_high,
        work_seconds_each=work_each, reps=reps,
        recovery_low=50, recovery_high=60, recovery_seconds=recovery_each,
    )
    main_set = [main_block]

    # --- Assemble + real TSS (durable) ---
    markdown = assembler.build_markdown(warmup, main_set, cooldown)
    est_tss, est_if = assembler.compute_tss_if(warmup, main_set, cooldown,
                                                mode=req.mode)

    sid = str(uuid.uuid4())[:8]
    summary = (f"{req.requested_zone} {reps}x{work_each//60}min "
               f"[PHASE-1 placeholder]")

    session = GeneratedSession(
        id=sid,
        generated_at=CatalogEntry.now_iso(),
        mode=req.mode,
        dominant_zone=req.requested_zone,
        structural_pattern="classic_interval",  # placeholder label
        complementary_zones=[],
        warmup=warmup,
        main_set=main_set,
        cooldown=cooldown,
        estimated_tss=round(est_tss, 1),
        estimated_if=round(est_if, 3),
        feasibility=Feasibility(satisfied=True),
        summary=summary,
        markdown_output=markdown,
        progression_id=progression_id,
        generation_seed=seed,
    )

    if catalog is not None:
        # Mode-safe warmup duration: power mode has a single ramp; HR mode has
        # a staircase in warmup.steps and ramp is None (this previously crashed
        # with AttributeError on HR + catalog).
        warmup_dur = warmup.prep.duration_seconds
        if warmup.steps:
            warmup_dur += sum(s.duration_seconds for s in warmup.steps)
        elif warmup.ramp is not None:
            warmup_dur += warmup.ramp.duration_seconds
        total_dur = warmup_dur + sum(
            (b.repeats * sum(s.duration_seconds for s in b.steps))
            if hasattr(b, "repeats") else b.duration_seconds
            for b in main_set
        ) + sum(
            (b.repeats * sum(s.duration_seconds for s in b.steps))
            if hasattr(b, "repeats") else b.duration_seconds
            for b in cooldown
        )
        catalog.add(CatalogEntry(
            id=sid, generated_at=session.generated_at, mode=req.mode,
            dominant_zone=req.requested_zone,
            structural_pattern=session.structural_pattern,
            complementary=[], duration_seconds=total_dur,
            estimated_tss=session.estimated_tss,
            estimated_if=session.estimated_if,
            progression_id=progression_id, summary=summary,
            markdown=markdown,
        ))

    return session
