"""
generator_v2.py — Phase-2 orchestration (Claude reasoning + deterministic core).

Flow (spec Section 9):
  request -> conflict checks -> ask Claude for a structural proposal (tool-use)
  -> VALIDATE proposal against hard rules -> rebuild with the core ->
  assemble mandatory structure + main set -> compute real TSS -> catalog.

If a proposal is rejected, it is DISCARDED and re-requested (up to a small
retry budget). Python never silently "fixes" a bad proposal and never accepts
one blind. The math, rendering, and output gate remain 100% deterministic.
"""

from __future__ import annotations
import uuid
import random
from typing import Optional

from .models import GenerationRequest, GeneratedSession, Feasibility
from .zones import zone_by_name
from . import structure as struct
from . import assembler
from . import tss as tssmod
from .catalog import Catalog, CatalogEntry
from .claude_client import Transport, request_proposal
from .proposal import (validate_proposal, verify_tss_target, verify_if_target,
                       ProposalRejected)
from .build_from_proposal import build_main_set, build_hr_staircase_tuples
from .resolve_intensity import (resolve_proposal_intensity, IntensityInfeasible)


# Provisional default warmup/cooldown ramp ranges for POWER mode. These remain
# deterministic in both phases (warmup/cooldown shape is structural, not the
# creative main-set work). Claude may later own these too, but Phase 2 keeps
# them stable to isolate the creative surface to the main set + HR staircase.
_WARMUP_RAMP = (45, 75)
_COOLDOWN_RAMP = (75, 45)
_MAX_RETRIES = 3


def generate_single_v2(req: GenerationRequest, *,
                       transport: Transport,
                       catalog: Optional[Catalog] = None,
                       use_web_search: bool = False,
                       progression_id: Optional[str] = None) -> GeneratedSession:
    if req.mode not in ("power", "hr"):
        raise ValueError("mode must be 'power' or 'hr'")
    if not req.requested_zone:
        raise ValueError("requested_zone is required")
    # Fail fast: validate the zone name locally before spending any API calls
    # (previously an invalid zone from e.g. the natural-language parser would
    # burn all 3 retries against the API before failing).
    zone_by_name(req.mode, req.requested_zone)

    # Hard-constraint conflict detection (spec 16.3) before spending an API call.
    struct.check_duration_vs_tss(
        req.target_tss, req.target_if, req.max_available_seconds
    )

    recent = []
    if catalog is not None:
        recent = catalog.recent(mode=req.mode, dominant_zone=req.requested_zone)

    # --- Ask Claude, validate, build, and verify TSS target; retry as needed ---
    last_error: Optional[str] = None
    proposal: Optional[dict] = None
    warmup = cooldown = main_set = None
    markdown = None
    est_tss = est_if = None

    # --- Session-level algebra (spec 16.1, pure math, engine's territory) ---
    # TSS + IF given without a duration -> the duration is implied; derive it.
    # All three given -> they must be mutually consistent; report if not.
    target_duration = req.target_duration_seconds
    if req.target_tss is not None and req.target_if is not None:
        implied = tssmod.duration_from(req.target_tss, req.target_if)
        if target_duration is None:
            target_duration = int(round(implied))
        elif abs(implied - target_duration) / target_duration > 0.05:
            raise struct.ConstraintConflict(
                f"over-determined request is inconsistent: TSS "
                f"{req.target_tss:g} at IF {req.target_if:g} implies "
                f"{implied/60:.1f} min, but the requested duration is "
                f"{target_duration/60:.1f} min. Adjust one of the three."
            )

    # Budget: the strictest of the given caps. The floor only applies when the
    # user gave (or the algebra implied) a TARGET duration; max_available is a
    # ceiling, never a target to fill (A3).
    _caps = [x for x in (target_duration, req.max_available_seconds) if x]
    budget = min(_caps) if _caps else None
    floor_applies = target_duration is not None

    # M4: zone-bounded feasibility (no user IF needed) — hard conflict with
    # numbers BEFORE spending any API call.
    struct.check_zone_feasibility(req.mode, req.requested_zone,
                                  req.target_tss, req.target_if, budget)
    for _attempt in range(_MAX_RETRIES):
        candidate = request_proposal(
            transport=transport, mode=req.mode, zone=req.requested_zone,
            target_duration_seconds=target_duration,
            target_tss=req.target_tss, target_if=req.target_if,
            recent=recent, use_web_search=use_web_search,
            rejection_feedback=last_error,  # A4: correct, don't guess blind
        )
        try:
            # Effective structure durations — what the builder will ACTUALLY
            # use (defaults filled; in HR the real staircase sum governs the
            # warmup). Validated against the budget so the ceiling cannot be
            # bypassed by omitting fields (C2) or by declaring a warmup that
            # disagrees with the staircase (M2, budget side).
            warmup_s = candidate.get("warmup_seconds", struct.WARMUP_RAMP_MAX)
            prep_s = candidate.get("prep_seconds", struct.PREP_MAX_SECONDS)
            cooldown_s = candidate.get("cooldown_seconds", struct.COOLDOWN_MAX)
            stair: Optional[list] = None
            if req.mode == "hr":
                stair = build_hr_staircase_tuples(candidate) or \
                    list(struct.DEFAULT_HR_STAIRCASE)
                warmup_s = sum(s[2] for s in stair)

            validate_proposal(candidate, mode=req.mode,
                              dominant_zone=req.requested_zone,
                              total_budget_seconds=budget,
                              enforce_floor=floor_applies,
                              structure_seconds=(warmup_s, prep_s, cooldown_s))

            # --- Deterministic intensity resolution (C3, spec 16.2) ---
            # Power mode with a TSS/IF target: Claude fixed the STRUCTURE;
            # the engine now solves the one free variable — the dominant
            # work intensity — in closed form. Never left to guessing.
            if req.mode == "power" and (req.target_tss is not None
                                        or req.target_if is not None):
                structure_segments = [
                    tssmod.Segment(float(warmup_s),
                                   sum(_WARMUP_RAMP) / 2.0 / 100.0),
                    tssmod.Segment(float(prep_s),
                                   (struct.PREP_LOW + struct.PREP_HIGH) / 2.0 / 100.0),
                    tssmod.Segment(float(cooldown_s),
                                   sum(_COOLDOWN_RAMP) / 2.0 / 100.0),
                ]
                if req.target_if is not None:
                    np_target = req.target_if
                else:
                    total_s = warmup_s + prep_s + cooldown_s + \
                        _proposal_main_seconds(candidate)
                    np_target = tssmod.if_from(req.target_tss, total_s)
                try:
                    candidate = resolve_proposal_intensity(
                        candidate, mode=req.mode,
                        dominant_zone=req.requested_zone,
                        np_target_frac=np_target,
                        structure_segments=structure_segments,
                    )
                except IntensityInfeasible as e:
                    raise ProposalRejected(str(e))

            if req.mode == "power":
                w = struct.build_warmup(req.mode, *_WARMUP_RAMP,
                                        ramp_seconds=warmup_s, prep_seconds=prep_s)
                c = struct.build_cooldown_ramp(req.mode, *_COOLDOWN_RAMP,
                                               seconds=cooldown_s)
            else:
                w = struct.build_warmup_hr_staircase(stair, prep_seconds=prep_s)
                c = struct.build_cooldown_hr_single(60, 70, seconds=cooldown_s)

            m = build_main_set(req.mode, candidate)
            md = assembler.build_markdown(w, m, c)
            t_tss, t_if = assembler.compute_tss_if(w, m, c, mode=req.mode)

            # Target verification (spec 16.3): only meaningful once the FULL
            # session (incl. warmup/cooldown) is built, since those contribute
            # to the real TSS/IF too. With the deterministic resolution above,
            # these now pass by construction (rounding-level deviations only);
            # they remain as the final honesty gate.
            if req.target_tss is not None:
                verify_tss_target(t_tss, req.target_tss)
            if req.mode == "power" and req.target_if is not None:
                verify_if_target(t_if, req.target_if)

            proposal, warmup, cooldown, main_set = candidate, w, c, m
            markdown, est_tss, est_if = md, t_tss, t_if
            break
        except ProposalRejected as e:
            last_error = str(e)
            continue
    if proposal is None:
        raise ProposalRejected(
            f"no valid proposal after {_MAX_RETRIES} attempts; last: {last_error}"
        )

    sid = str(uuid.uuid4())[:8]
    summary = proposal.get("summary", f"{req.requested_zone} session")
    complementary = [c["zone"] for c in proposal.get("complementary_stimuli", [])]

    session = GeneratedSession(
        id=sid, generated_at=CatalogEntry.now_iso(), mode=req.mode,
        dominant_zone=req.requested_zone,
        structural_pattern=proposal.get("structural_pattern"),
        complementary_zones=complementary,
        warmup=warmup, main_set=main_set, cooldown=cooldown,
        estimated_tss=round(est_tss, 1), estimated_if=round(est_if, 3),
        feasibility=Feasibility(satisfied=True),
        summary=summary, markdown_output=markdown,
        progression_id=progression_id,
    )

    if catalog is not None:
        total_dur = _total_duration(warmup, main_set, cooldown)
        catalog.add(CatalogEntry(
            id=sid, generated_at=session.generated_at, mode=req.mode,
            dominant_zone=req.requested_zone,
            structural_pattern=session.structural_pattern,
            complementary=complementary, duration_seconds=total_dur,
            estimated_tss=session.estimated_tss, estimated_if=session.estimated_if,
            progression_id=progression_id, summary=summary, markdown=markdown,
        ))

    return session


def _elements_duration(elements: list) -> int:
    total = 0
    for el in elements:
        if hasattr(el, "repeats"):
            total += el.repeats * sum(s.duration_seconds for s in el.steps)
        else:
            total += el.duration_seconds
    return total


def _proposal_main_seconds(proposal: dict) -> int:
    """Total main-set seconds of a raw proposal dict (repeats expanded)."""
    total = 0
    for el in proposal["main_set"]:
        if el.get("element") == "step":
            total += el["duration_seconds"]
        else:
            total += el.get("repeats", 1) * sum(
                s["duration_seconds"] for s in el.get("steps", []))
    return total


def _total_duration(warmup, main_set, cooldown) -> int:
    warm = warmup.prep.duration_seconds
    if warmup.steps:
        warm += sum(s.duration_seconds for s in warmup.steps)
    elif warmup.ramp is not None:
        warm += warmup.ramp.duration_seconds
    return warm + _elements_duration(main_set) + _elements_duration(cooldown)
