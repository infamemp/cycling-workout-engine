"""
generate_progression.py — Orchestrate a full reasoned progression
(spec Section 15) under the no-KB free-reasoning rule (Section 9.6).

Flow: ask Claude for a reasoned progression -> validate every session ->
build/render each with the deterministic core -> link them with one shared
progression_id (so the catalog's progression exemption applies, Section 17) ->
return the ordered list of GeneratedSession plus the reasoning/graduation note.
"""

from __future__ import annotations
import uuid
from dataclasses import dataclass
from typing import Optional

from .models import GenerationRequest, GeneratedSession, Feasibility
from .zones import zone_by_name
from . import structure as struct
from . import assembler
from .catalog import Catalog, CatalogEntry
from .claude_client import Transport, request_progression
from .progression import validate_progression
from .proposal import ProposalRejected
from .build_from_proposal import build_main_set, build_hr_staircase_tuples

_WARMUP_RAMP = (45, 75)
_COOLDOWN_RAMP = (75, 45)
_MAX_RETRIES = 3


@dataclass
class ProgressionResult:
    progression_id: str
    reasoning: str
    graduation_note: Optional[str]
    sessions: list[GeneratedSession]


def generate_progression(req: GenerationRequest, *,
                         transport: Transport,
                         catalog: Optional[Catalog] = None,
                         use_web_search: bool = False,
                         initial_session_seconds: Optional[int] = None) -> ProgressionResult:
    if req.mode not in ("power", "hr"):
        raise ValueError("mode must be 'power' or 'hr'")
    if not req.requested_zone:
        raise ValueError("requested_zone is required")
    # Fail fast: validate the zone name locally before spending any API calls.
    zone_by_name(req.mode, req.requested_zone)

    # Default the Day-1 budget from the request's target duration if not given.
    if initial_session_seconds is None:
        initial_session_seconds = req.target_duration_seconds

    recent = []
    if catalog is not None:
        recent = catalog.recent(mode=req.mode, dominant_zone=req.requested_zone)

    # Ask Claude for a reasoned progression; validate; retry on rejection.
    # Per-session budgets (spec 15): Day 1 must fit the initial budget exactly;
    # later sessions are capped by the user's max (Case B) if one was given.
    # If no max was given (Case A), later sessions have no hard cap — the
    # engine researches and grows toward the physiological ceiling itself.
    last_error: Optional[str] = None
    progression: Optional[dict] = None
    effective_structures: list[tuple[int, int, int]] = []
    for _ in range(_MAX_RETRIES):
        candidate = request_progression(
            transport=transport, mode=req.mode, zone=req.requested_zone,
            initial_session_seconds=initial_session_seconds,
            max_session_seconds=req.max_available_seconds,
            recent=recent, use_web_search=use_web_search,
            rejection_feedback=last_error,  # A4: correct, don't guess blind
        )
        try:
            sessions_raw = candidate.get("sessions") or []
            n = len(sessions_raw)
            # Effective per-session structure durations (defaults filled; HR
            # staircase sum governs the warmup) — same C2 hardening as
            # generate_single_v2, so the ceiling can't be bypassed.
            structures: list[tuple[int, int, int]] = []
            for sess in sessions_raw:
                w = sess.get("warmup_seconds", struct.WARMUP_RAMP_MAX)
                p = sess.get("prep_seconds", struct.PREP_MAX_SECONDS)
                cd = sess.get("cooldown_seconds", struct.COOLDOWN_MAX)
                if req.mode == "hr":
                    st = build_hr_staircase_tuples(sess) or \
                        list(struct.DEFAULT_HR_STAIRCASE)
                    w = sum(x[2] for x in st)
                structures.append((w, p, cd))
            session_budgets = [
                initial_session_seconds if i == 0 else req.max_available_seconds
                for i in range(n)
            ]
            # Day 1's budget is a TARGET (floor applies, spec 15: Day 1 fits
            # the initial duration); later budgets come from max_available,
            # which is a CEILING only (A3 — never a target to fill).
            floor_flags = [
                (i == 0 and initial_session_seconds is not None)
                for i in range(n)
            ]
            validate_progression(candidate, mode=req.mode,
                                 dominant_zone=req.requested_zone,
                                 session_budgets=session_budgets,
                                 session_structures=structures,
                                 session_floor_flags=floor_flags)
            progression = candidate
            effective_structures = structures
            break
        except ProposalRejected as e:
            last_error = str(e)
            continue
    if progression is None:
        raise ProposalRejected(
            f"no valid progression after {_MAX_RETRIES} attempts; last: {last_error}"
        )

    prog_id = "prog_" + str(uuid.uuid4())[:8]
    sessions: list[GeneratedSession] = []

    for idx, sess_proposal in enumerate(progression["sessions"], start=1):
        # Use the SAME effective durations that were validated (C2): defaults
        # filled, HR staircase sum governing the warmup.
        warmup_s, prep_s, cooldown_s = effective_structures[idx - 1]

        # Mandatory structure per session (deterministic), mode-dependent.
        if req.mode == "power":
            warmup = struct.build_warmup(req.mode, *_WARMUP_RAMP,
                                         ramp_seconds=warmup_s, prep_seconds=prep_s)
            cooldown = struct.build_cooldown_ramp(req.mode, *_COOLDOWN_RAMP,
                                                  seconds=cooldown_s)
        else:
            stair = build_hr_staircase_tuples(sess_proposal) or \
                list(struct.DEFAULT_HR_STAIRCASE)
            warmup = struct.build_warmup_hr_staircase(stair, prep_seconds=prep_s)
            cooldown = struct.build_cooldown_hr_single(60, 70, seconds=cooldown_s)

        main_set = build_main_set(req.mode, sess_proposal)
        markdown = assembler.build_markdown(warmup, main_set, cooldown)
        est_tss, est_if = assembler.compute_tss_if(warmup, main_set, cooldown,
                                                    mode=req.mode)

        sid = str(uuid.uuid4())[:8]
        summary = sess_proposal.get("summary",
                                    f"{req.requested_zone} session {idx}")
        complementary = [c["zone"]
                         for c in sess_proposal.get("complementary_stimuli", [])]

        session = GeneratedSession(
            id=sid, generated_at=CatalogEntry.now_iso(), mode=req.mode,
            dominant_zone=req.requested_zone,
            structural_pattern=sess_proposal.get("structural_pattern"),
            complementary_zones=complementary,
            warmup=warmup, main_set=main_set, cooldown=cooldown,
            estimated_tss=round(est_tss, 1), estimated_if=round(est_if, 3),
            feasibility=Feasibility(satisfied=True),
            summary=f"[{idx}/{len(progression['sessions'])}] {summary}",
            markdown_output=markdown, progression_id=prog_id,
        )
        sessions.append(session)

        if catalog is not None:
            catalog.add(CatalogEntry(
                id=sid, generated_at=session.generated_at, mode=req.mode,
                dominant_zone=req.requested_zone,
                structural_pattern=session.structural_pattern,
                complementary=complementary,
                duration_seconds=None,
                estimated_tss=session.estimated_tss,
                estimated_if=session.estimated_if,
                progression_id=prog_id, summary=session.summary,
                markdown=markdown,
            ))

    return ProgressionResult(
        progression_id=prog_id,
        reasoning=progression.get("reasoning", ""),
        graduation_note=progression.get("graduation_note"),
        sessions=sessions,
    )
