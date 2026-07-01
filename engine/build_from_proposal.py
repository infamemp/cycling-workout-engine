"""
build_from_proposal.py — Convert a VALIDATED Claude proposal into engine
components (Step / RepeatBlock), deriving RPE and rendering each line with the
deterministic core. Claude supplied structural intent; Python produces the
actual, validated, rendered objects.

Precondition: validate_proposal() has already passed for this proposal.
"""

from __future__ import annotations
from .models import Step, RepeatBlock
from .rpe import rpe_for_flat
from .render import render_step_line


def _build_step(mode: str, st: dict, *, default_role: str = "work") -> Step:
    lo, hi = st["low_pct"], st["high_pct"]
    role = "recovery" if st.get("is_recovery") else default_role
    rpe_lo, rpe_hi = rpe_for_flat(mode, lo, hi)
    cad_lo = st.get("cadence_low")
    cad_hi = st.get("cadence_high")
    return Step(
        role=role,
        duration_seconds=st["duration_seconds"],
        flat_low=lo, flat_high=hi,
        cadence_low=cad_lo, cadence_high=cad_hi,
        rpe_low=rpe_lo, rpe_high=rpe_hi,
        rendering=render_step_line(
            mode=mode, duration_seconds=st["duration_seconds"],
            flat_low=lo, flat_high=hi,
            cadence_low=cad_lo, cadence_high=cad_hi,
            rpe_low=rpe_lo, rpe_high=rpe_hi,
        ),
    )


def build_main_set(mode: str, proposal: dict) -> list:
    """Return list[Step | RepeatBlock] from a validated proposal's main_set."""
    out: list = []
    for el in proposal["main_set"]:
        if el["element"] == "step":
            out.append(_build_step(mode, el))
        else:  # repeat
            steps = [_build_step(mode, s) for s in el["steps"]]
            out.append(RepeatBlock(repeats=el["repeats"], steps=steps))
    return out


def build_hr_staircase_tuples(proposal: dict) -> list[tuple[int, int, int]]:
    """Extract the HR warmup staircase as (low, high, seconds) tuples, if the
    proposal provided one (HR mode). Returns [] if absent."""
    stair = proposal.get("hr_warmup_staircase") or []
    return [(s[0], s[1], s[2]) for s in stair]
