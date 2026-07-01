"""
proposal.py — The contract between the Claude reasoning layer and the
deterministic core (spec Section 9).

Claude proposes a workout STRUCTURE via tool-use, returning JSON that matches
PROPOSAL_TOOL_SCHEMA. Python then VALIDATES every proposal against the hard
rules before accepting it. A rejected proposal is discarded and re-requested —
never silently "fixed", never accepted blind.

Division of responsibility (confirmed):
  - Claude decides: main-set structure (reps, durations, recoveries, pattern),
    intensity %s within the requested zone, optional subordinate complementary
    stimuli, HR staircase shape, progression week-to-week shape.
  - Python owns: validation, TSS/IF math, rendering, output gate. Claude never
    does the math and never produces the final syntax directly.
"""

from __future__ import annotations
from .zones import zones_for_mode, zone_by_name


# --- The tool schema Claude must fill (passed to the API as a tool) ----------
# Claude returns ONLY structural intent; Python turns it into validated output.

PROPOSAL_TOOL_SCHEMA = {
    "name": "propose_workout",
    "description": (
        "Propose the STRUCTURE of one indoor cycling workout's main set. "
        "Return structural intent only — do NOT compute TSS/IF and do NOT "
        "write intervals.icu syntax; the engine does that. Respect the "
        "requested zone as the dominant stimulus; any complementary stimuli "
        "must be subordinate (less time-in-zone). All intensities are integer "
        "percent ranges within the mode's zone system."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["structural_pattern", "main_set", "summary"],
        "properties": {
            "structural_pattern": {
                "type": "string",
                "enum": ["continuous", "classic_interval", "pyramidal",
                         "ladder", "over_under", "progressive", "divided_split"],
            },
            "main_set": {
                "type": "array",
                "minItems": 1,
                "description": "Ordered elements: each is a single step or a "
                               "repeat block (Nx). Repeat blocks are NOT nested.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["element"],
                    "properties": {
                        "element": {"type": "string", "enum": ["step", "repeat"]},
                        # for element=step
                        "duration_seconds": {"type": "integer", "minimum": 1},
                        "low_pct": {"type": "integer", "minimum": 0},
                        "high_pct": {"type": "integer", "minimum": 0},
                        "zone_name": {"type": "string",
                                      "description": "Which zone this segment "
                                      "belongs to (dominant or a complementary)."},
                        "is_recovery": {"type": "boolean"},
                        "cadence_low": {"type": "integer"},
                        "cadence_high": {"type": "integer"},
                        # for element=repeat
                        "repeats": {"type": "integer", "minimum": 1},
                        "steps": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["duration_seconds", "low_pct", "high_pct", "zone_name"],
                                "properties": {
                                    "duration_seconds": {"type": "integer", "minimum": 1},
                                    "low_pct": {"type": "integer", "minimum": 0},
                                    "high_pct": {"type": "integer", "minimum": 0},
                                    "zone_name": {"type": "string"},
                                    "is_recovery": {"type": "boolean"},
                                    "cadence_low": {"type": "integer"},
                                    "cadence_high": {"type": "integer"},
                                },
                            },
                        },
                    },
                },
            },
            "complementary_stimuli": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["zone"],
                    "properties": {
                        "zone": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                },
            },
            # HR mode only: staircase warmup shape (number of steps engine-free)
            "hr_warmup_staircase": {
                "type": "array",
                "description": "HR mode only. Ascending steps; each [low%, high%, seconds].",
                "items": {
                    "type": "array",
                    "minItems": 3, "maxItems": 3,
                    "items": {"type": "integer"},
                },
            },
            "summary": {"type": "string"},
            "warmup_seconds": {
                "type": "integer", "minimum": 1,
                "description": "Engine-reasoned warmup duration (ramp or "
                "staircase total). Cap 600s (10 min); size it to the session "
                "budget — keep it short in short sessions.",
            },
            "prep_seconds": {
                "type": "integer", "minimum": 60, "maximum": 120,
                "description": "Prep block duration, 60-120s (1-2 min), always "
                "present.",
            },
            "cooldown_seconds": {
                "type": "integer", "minimum": 1,
                "description": "Engine-reasoned cooldown duration. Cap 300s "
                "(5 min); size to budget.",
            },
        },
    },
}


# --- Validation of a returned proposal (spec 9: validate before accept) ------

class ProposalRejected(ValueError):
    """A Claude proposal violated a hard rule. Discard and re-request."""


def _zone_names(mode: str) -> set[str]:
    return {z.name for z in zones_for_mode(mode)}


def _check_step(mode: str, step: dict, valid_zones: set[str], dominant: str) -> None:
    lo, hi = step["low_pct"], step["high_pct"]
    if lo > hi:
        raise ProposalRejected(f"step low_pct {lo} > high_pct {hi}")
    if lo < 0 or hi < 0:
        raise ProposalRejected("percent values must be non-negative")

    # Recovery segments are "whatever is easy enough" — they are NOT required to
    # sit exactly within a named zone's bounds (a recovery may straddle the
    # Recovery/Aerobic boundary, etc.). Only sanity-check they are genuinely
    # easy, not accidentally hard.
    if step.get("is_recovery"):
        # An easy recovery should not exceed roughly endurance/aerobic intensity.
        ceiling = 85
        if lo > ceiling:
            raise ProposalRejected(
                f"recovery intensity {lo}-{hi}% too hard (>{ceiling}%)"
            )
        return

    # Work segments: zone name must be valid and intensity must sit within it.
    zname = step.get("zone_name", dominant)
    if zname not in valid_zones:
        raise ProposalRejected(
            f"zone {zname!r} not valid in {mode} system (cross-mode mixing forbidden)"
        )
    z = zone_by_name(mode, zname)
    hi_bound = z.high_pct if z.high_pct is not None else max(hi, z.low_pct)
    if hi < z.low_pct or lo > hi_bound:
        raise ProposalRejected(
            f"intensity {lo}-{hi}% outside zone {zname} bounds "
            f"[{z.low_pct},{z.high_pct}]"
        )


def _collect_used_zones(main_set: list, dominant_zone: str) -> set[str]:
    """Collect all non-dominant, non-recovery zone names actually used across
    main_set (steps and repeat-block inner steps), for the metadata-honesty
    check in validate_proposal."""
    used: set[str] = set()
    for el in main_set:
        if el.get("element") == "step":
            if not el.get("is_recovery"):
                z = el.get("zone_name", dominant_zone)
                if z != dominant_zone:
                    used.add(z)
        elif el.get("element") == "repeat":
            for st in el.get("steps", []):
                if not st.get("is_recovery"):
                    z = st.get("zone_name", dominant_zone)
                    if z != dominant_zone:
                        used.add(z)
    return used


def validate_proposal(proposal: dict, *, mode: str, dominant_zone: str,
                      total_budget_seconds: int | None = None) -> None:
    """Validate a Claude proposal against the hard rules. Raises
    ProposalRejected on the first violation; returns None if acceptable.

    Hard rules enforced here (spec 4, 8, 11, 12, 17):
      - all zone names valid in the chosen mode (no cross-mode mixing)
      - work intensities within their named zone bounds
      - no nested repeats
      - dominant stimulus must actually dominate (most work time-in-zone)
      - structural duration caps (warmup<=600s, prep 60-120s, cooldown<=300s)
      - if a total budget is given: warmup+prep+cooldown+main_set <= budget
        (pure arithmetic conservation of the total, NOT a training rule)
    """
    valid = _zone_names(mode)
    if dominant_zone not in valid:
        raise ProposalRejected(f"dominant zone {dominant_zone!r} invalid for {mode}")

    if not proposal.get("main_set"):
        raise ProposalRejected("main_set is empty")

    # --- Structural duration caps (spec 11: these are maxima, not targets) ---
    warmup_s = proposal.get("warmup_seconds")
    prep_s = proposal.get("prep_seconds")
    cooldown_s = proposal.get("cooldown_seconds")
    if warmup_s is not None and warmup_s > 600:
        raise ProposalRejected(f"warmup {warmup_s}s exceeds 600s cap")
    if prep_s is not None and not (60 <= prep_s <= 120):
        raise ProposalRejected(f"prep {prep_s}s outside 60-120s")
    if cooldown_s is not None and cooldown_s > 300:
        raise ProposalRejected(f"cooldown {cooldown_s}s exceeds 300s cap")

    dominant_work = 0
    other_work = 0
    main_set_seconds = 0

    for el in proposal["main_set"]:
        kind = el.get("element")
        if kind == "step":
            if "steps" in el or "repeats" in el:
                raise ProposalRejected("step element must not carry repeat fields")
            _check_step(mode, el, valid, dominant_zone)
            main_set_seconds += el["duration_seconds"]
            if not el.get("is_recovery"):
                z = el.get("zone_name", dominant_zone)
                t = el["duration_seconds"]
                if z == dominant_zone:
                    dominant_work += t
                else:
                    other_work += t
        elif kind == "repeat":
            inner = el.get("steps")
            if not inner:
                raise ProposalRejected("repeat element missing steps")
            block_seconds = 0
            for st in inner:
                if "element" in st:
                    raise ProposalRejected("nested repeats are forbidden")
                _check_step(mode, st, valid, dominant_zone)
                block_seconds += st["duration_seconds"]
                if not st.get("is_recovery"):
                    z = st.get("zone_name", dominant_zone)
                    t = st["duration_seconds"] * el["repeats"]
                    if z == dominant_zone:
                        dominant_work += t
                    else:
                        other_work += t
            main_set_seconds += block_seconds * el["repeats"]
        else:
            raise ProposalRejected(f"unknown element kind {kind!r}")

    # Dominant/subordinate boundary (spec 17): requested zone must dominate.
    if dominant_work <= 0:
        raise ProposalRejected("no work in the dominant (requested) zone")
    if other_work > dominant_work:
        raise ProposalRejected(
            f"complementary work ({other_work}s) exceeds dominant "
            f"({dominant_work}s) — requested stimulus must dominate"
        )

    # Metadata honesty: any non-dominant, non-recovery zone actually used in
    # main_set must be declared in complementary_stimuli, so the reported
    # complementary_zones on the session accurately reflects what was built.
    declared = {c["zone"] for c in proposal.get("complementary_stimuli", [])}
    used_other_zones = _collect_used_zones(proposal["main_set"], dominant_zone)
    undeclared = used_other_zones - declared
    if undeclared:
        raise ProposalRejected(
            f"zones {sorted(undeclared)} are used in main_set but not "
            f"declared in complementary_stimuli — metadata must match what "
            f"was actually built"
        )

    # --- Budget conservation (pure arithmetic, spec 15) ---
    if total_budget_seconds is not None:
        # Use proposed structure durations if present, else 0 (caller may fill).
        structure = (warmup_s or 0) + (prep_s or 0) + (cooldown_s or 0)
        total = structure + main_set_seconds
        if total > total_budget_seconds:
            raise ProposalRejected(
                f"session total {total}s (warmup {warmup_s or 0} + prep "
                f"{prep_s or 0} + cooldown {cooldown_s or 0} + main "
                f"{main_set_seconds}) exceeds budget {total_budget_seconds}s "
                f"by {total - total_budget_seconds}s"
            )


# --- TSS/IF target verification (spec 16.3 — report, never silently accept) --

_TSS_TOLERANCE_FRACTION = 0.10  # accept within +/-10% of the requested target


def verify_tss_target(proposal_segments_tss: float, target_tss: float) -> None:
    """Compare the ACTUAL computed TSS of a built proposal against the user's
    target. Raises ProposalRejected if the deviation exceeds tolerance —
    this closes the gap where a target_tss was requested but never checked
    against what was actually produced (spec 16.3: report, never force)."""
    if target_tss <= 0:
        return
    deviation = abs(proposal_segments_tss - target_tss) / target_tss
    if deviation > _TSS_TOLERANCE_FRACTION:
        raise ProposalRejected(
            f"resulting TSS {proposal_segments_tss:.1f} deviates "
            f"{deviation*100:.0f}% from the requested target {target_tss:g} "
            f"(tolerance is {_TSS_TOLERANCE_FRACTION*100:.0f}%)"
        )
