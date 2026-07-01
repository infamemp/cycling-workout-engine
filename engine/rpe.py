"""
rpe.py — RPE derivation (spec Section 6.3).

Two rules, depending on segment type:

  - Flat segment: take the MIDPOINT of the % range, find its zone, use that
    zone's RPE band (spec 6.2). E.g. 45-55% -> mid 50% -> Recovery -> [1,2].

  - Ramp segment (crosses zones): RPE spans from the FLOOR of the lower
    endpoint's zone band to the CEILING of the upper endpoint's zone band.
    E.g. 45-75% -> lower 45%=Recovery(floor 1), upper 75%=Endurance(ceil 4)
    -> [1,4]. The rule is fixed; the resulting numbers vary with the ramp.

RPE is ALWAYS a range (spec 6.1). Single values only occur naturally when the
band collapses (e.g. [1,1] or [10,10]).
"""

from __future__ import annotations
from .zones import zone_for_percent


def rpe_for_flat(mode: str, low_pct: float, high_pct: float) -> tuple[int, int]:
    """RPE band for a flat-intensity segment via the midpoint method."""
    midpoint = (low_pct + high_pct) / 2.0
    z = zone_for_percent(mode, midpoint)
    return (z.rpe_low, z.rpe_high)


def rpe_for_ramp(mode: str, start_pct: float, end_pct: float) -> tuple[int, int]:
    """RPE band for a ramp segment via the endpoint-span method.

    Works for ascending (start<end) or descending (start>end) ramps:
    the lower *percent* endpoint contributes the floor, the higher the ceiling.
    """
    lower = min(start_pct, end_pct)
    upper = max(start_pct, end_pct)
    z_lower = zone_for_percent(mode, lower)
    z_upper = zone_for_percent(mode, upper)
    return (z_lower.rpe_low, z_upper.rpe_high)
