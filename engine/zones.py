"""
zones.py — Fixed Friel preset zones (spec Section 4).

These are genuinely fixed data, so they live in code. The two systems
(power %FTP, HR %LTHR) are INDEPENDENT and NEVER cross-correlated:
if the user asks for power, only POWER_ZONES is used; for HR, only HR_ZONES.
Zone names overlap (e.g. "Tempo" exists in both) but they are different
systems that merely share names — they are never mapped to each other.

RPE bands per zone come from the project's confirmed Section 6.2 table,
which is the canonical source (NOT the Coggan column in the intervals.icu
reference file). Friel defines the zones; Coggan & Allen is only the
starting reference for the RPE correlation.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Zone:
    """A single training zone. Percent bounds are inclusive lower, exclusive
    upper for interior zones; the top zone is open-ended (high=None)."""
    name: str
    low_pct: int
    high_pct: Optional[int]  # None = open-ended (e.g. Neuromuscular 150%+)
    rpe_low: int
    rpe_high: int

    def contains(self, pct: float) -> bool:
        if pct < self.low_pct:
            return False
        if self.high_pct is None:
            return True
        return pct < self.high_pct

    def midpoint_pct(self) -> Optional[float]:
        """Representative percent for the zone; None for open-ended top zone."""
        if self.high_pct is None:
            return None
        return (self.low_pct + self.high_pct) / 2.0


# --- Friel POWER zones, % of FTP (spec 4.1) ---------------------------------
# Sweet Spot is an overlay (84-97%), handled separately, not in the sequence.
POWER_ZONES: tuple[Zone, ...] = (
    Zone("ActiveRecovery", 0, 55, 1, 2),
    Zone("Endurance", 55, 75, 2, 4),
    Zone("Tempo", 75, 90, 3, 5),
    Zone("Threshold", 90, 105, 5, 7),
    Zone("VO2Max", 105, 120, 7, 9),
    Zone("Anaerobic", 120, 150, 8, 10),
    Zone("Neuromuscular", 150, None, 9, 10),
)

POWER_SWEETSPOT = Zone("SweetSpot", 84, 97, 3, 5)  # overlay (spec 4.1)

# --- Friel HR zones, % of LTHR (spec 4.2) -----------------------------------
# RPE bands mirror the physiological-meaning mapping of Section 6.2.
HR_ZONES: tuple[Zone, ...] = (
    Zone("Recovery", 0, 81, 1, 2),
    Zone("Aerobic", 81, 90, 2, 4),
    Zone("Tempo", 90, 94, 3, 5),
    Zone("SubThreshold", 94, 100, 5, 7),
    Zone("SuperThreshold", 100, 103, 5, 7),
    Zone("AerobicCapacity", 103, 106, 7, 9),
    Zone("Anaerobic", 106, 114, 8, 10),
)


def zones_for_mode(mode: str) -> tuple[Zone, ...]:
    """Return the zone tuple for the given mode. Never mixes the two systems."""
    if mode == "power":
        return POWER_ZONES + (POWER_SWEETSPOT,)
    if mode == "hr":
        return HR_ZONES
    raise ValueError(f"unknown mode: {mode!r} (expected 'power' or 'hr')")


def zone_by_name(mode: str, name: str) -> Zone:
    for z in zones_for_mode(mode):
        if z.name == name:
            return z
    raise ValueError(f"zone {name!r} not found in {mode} zone system")


def zone_for_percent(mode: str, pct: float) -> Zone:
    """Find which zone a given percent falls into (used for RPE derivation of
    flat segments — spec 6.3 midpoint method). Sweet Spot overlay is excluded
    here since it overlaps Tempo/Threshold; sequential zones only."""
    seq = POWER_ZONES if mode == "power" else HR_ZONES
    for z in seq:
        if z.contains(pct):
            return z
    # Above all defined zones -> top zone
    return seq[-1]
