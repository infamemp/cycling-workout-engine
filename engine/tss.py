"""
tss.py — TSS / IF / duration resolution (spec Section 16).

Session-level algebra (exact):  TSS = duration_hours * IF^2 * 100
  => any one of {TSS, IF, duration} solves from the other two.

NP is computed with the SIMPLIFIED 4th-power-weighted formula (option A,
spec 16.2): no 30s rolling average. This is robust and exact for long
stable intervals; it diverges only on very short high-variability micro-
intervals, which are almost never designed against an exact TSS target.
The engine's TSS is a DESIGN-TIME ESTIMATE; intervals.icu/TrainingPeaks
computes the authoritative value on upload (spec 16.4).

All intensities here are fractions of FTP (1.0 == FTP == CP), so IF == NP/FTP
== NP when NP is already expressed as a fraction of FTP.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    """A constant-power segment for NP math. power_frac is fraction of FTP
    (e.g. 0.88 for 88%). For ramps, approximate with the midpoint fraction."""
    duration_seconds: float
    power_frac: float


# --- Core algebra -----------------------------------------------------------

def tss_from(duration_seconds: float, intensity_factor: float) -> float:
    hours = duration_seconds / 3600.0
    return hours * (intensity_factor ** 2) * 100.0


def duration_from(tss: float, intensity_factor: float) -> float:
    """Seconds required to reach `tss` at the given IF."""
    if intensity_factor <= 0:
        raise ValueError("IF must be > 0")
    hours = tss / ((intensity_factor ** 2) * 100.0)
    return hours * 3600.0


def if_from(tss: float, duration_seconds: float) -> float:
    """IF required to reach `tss` in the given duration."""
    if duration_seconds <= 0:
        raise ValueError("duration must be > 0")
    hours = duration_seconds / 3600.0
    return (tss / (hours * 100.0)) ** 0.5


# --- Normalized Power (simplified, spec 16.2) -------------------------------

def normalized_power_frac(segments: list[Segment]) -> float:
    """Simplified NP as a fraction of FTP: 4th-power-weighted average of
    segment powers. NP = ( sum(t_i * p_i^4) / sum(t_i) ) ^ (1/4)."""
    total_t = sum(s.duration_seconds for s in segments)
    if total_t <= 0:
        raise ValueError("total duration must be > 0")
    weighted = sum(s.duration_seconds * (s.power_frac ** 4) for s in segments)
    return (weighted / total_t) ** 0.25


def intensity_factor(segments: list[Segment]) -> float:
    """IF == NP/FTP; since powers are already fractions of FTP, IF == NP_frac."""
    return normalized_power_frac(segments)


def session_tss(segments: list[Segment]) -> float:
    """TSS of a fully-specified session (the real TSS of what was built)."""
    total_t = sum(s.duration_seconds for s in segments)
    return tss_from(total_t, intensity_factor(segments))


# --- Work-segment intensity resolution (spec 16.2, single unknown) ----------

def solve_work_power_frac(
    *,
    np_target_frac: float,
    total_seconds: float,
    known_segments: list[Segment],
    work_total_seconds: float,
) -> float:
    """Solve the one free variable — the work-segment power fraction — so the
    whole session hits np_target_frac. Closed-form (spec 16.2):

        P_work = [ (NP^4 * T_total - sum(t_i * p_i^4)) / t_work ] ^ (1/4)

    Returns the work power as a fraction of FTP. Raises if the result is not
    physically real (negative radicand) — caller treats that as infeasible.
    """
    if work_total_seconds <= 0:
        raise ValueError("work_total_seconds must be > 0")
    known_contrib = sum(s.duration_seconds * (s.power_frac ** 4) for s in known_segments)
    radicand = (np_target_frac ** 4 * total_seconds - known_contrib) / work_total_seconds
    if radicand < 0:
        raise InfeasibleError(
            "target intensity not reachable: required work power^4 is negative"
        )
    return radicand ** 0.25


class InfeasibleError(ValueError):
    """Raised when a TSS/IF target cannot be met within the given structure.
    Per spec 16.3 the engine reports this rather than forcing a value."""
