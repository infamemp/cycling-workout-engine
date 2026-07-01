"""
resolve_intensity.py — Deterministic work-segment intensity resolution
(spec Section 16.2/16.3/16.4). POWER MODE ONLY (NP/IF/TSS are power math).

Strict order (spec 16.2): the STRUCTURE is fixed first (by the reasoning
layer — reps, durations, recoveries, warmup/cooldown shape), WITHOUT
reference to TSS/IF. Only then is the one remaining free variable — the
dominant work-segment intensity — solved in closed form:

    P_work = [ (NP_target^4 * T_total - sum(t_i * p_i^4)) / t_work ] ^ (1/4)

Generalization for multiple dominant work steps (over/under, pyramids where
all steps are the dominant zone): the proposal's internal intensity RATIOS
between dominant steps are preserved (spec 16.2: the secondary intensity is
parametrized relative to the primary), so exactly ONE unknown x remains:

    step_i power = r_i * x,   r_i = proposed_mid_i / proposed_mid_first
    NP^4 * T = known + x^4 * sum(t_i * r_i^4)   ->  closed form for x.

Known segments (never touched): warmup, prep, cooldown, every recovery step,
and every complementary (non-dominant) step — their proposed values stand.

Infeasibility (spec 16.3): if the solved intensity falls outside the dominant
zone's bounds, this is a HARD infeasibility reported with concrete numbers
(including the closest achievable TSS at the zone edge) — never clamped,
never silently forced.

Rounding (spec 16.4): the solved center is rounded to an integer percent; the
output range keeps the proposal's width, shrunk symmetrically only if needed
to stay inside the zone (the solved center — the physiological target — is
preserved; the width is presentation). The reported TSS downstream is the
real TSS of the rounded, built session.
"""

from __future__ import annotations
import copy
from dataclasses import dataclass

from .zones import zone_by_name
from . import tss as tssmod


class IntensityInfeasible(ValueError):
    """Raised when the TSS/IF target cannot be met within the dominant zone
    for the fixed structure (spec 16.3: report with numbers, never force)."""


@dataclass(frozen=True)
class _WorkStep:
    seconds_total: float      # duration x repeats
    mid_frac: float           # proposed midpoint as fraction of FTP
    half_width_pct: float     # proposed (high-low)/2 in percent points


def _iter_main_steps(proposal: dict):
    """Yield (step_dict, occurrences) for every step in main_set, flattening
    repeat blocks (repeats -> occurrences)."""
    for el in proposal["main_set"]:
        if el.get("element") == "step":
            yield el, 1
        else:
            for st in el.get("steps", []):
                yield st, el.get("repeats", 1)


def _classify(proposal: dict, dominant_zone: str):
    """Split main_set steps into dominant work steps (the unknown) and known
    segments (recoveries + complementary steps, proposed values stand)."""
    work: list[_WorkStep] = []
    known: list[tssmod.Segment] = []
    for st, occ in _iter_main_steps(proposal):
        secs = float(st["duration_seconds"]) * occ
        mid = (st["low_pct"] + st["high_pct"]) / 2.0
        zname = st.get("zone_name", dominant_zone)
        if (not st.get("is_recovery")) and zname == dominant_zone:
            hw = (st["high_pct"] - st["low_pct"]) / 2.0
            work.append(_WorkStep(secs, mid / 100.0, hw))
        else:
            known.append(tssmod.Segment(secs, mid / 100.0))
    return work, known


def solve_dominant_intensity(*, work: list[_WorkStep],
                             known: list[tssmod.Segment],
                             np_target_frac: float) -> float:
    """Closed-form solve for x (the primary dominant intensity as a fraction
    of FTP), preserving the proposal's internal ratios between work steps."""
    if not work:
        raise IntensityInfeasible("no dominant work steps to resolve")
    ref = work[0].mid_frac
    if ref <= 0:
        raise IntensityInfeasible("reference work intensity is zero")
    ratios = [w.mid_frac / ref for w in work]
    total_t = sum(w.seconds_total for w in work) + \
        sum(s.duration_seconds for s in known)
    known_contrib = sum(s.duration_seconds * (s.power_frac ** 4) for s in known)
    ratio_weight = sum(w.seconds_total * (r ** 4)
                       for w, r in zip(work, ratios))
    radicand = ((np_target_frac ** 4) * total_t - known_contrib) / ratio_weight
    if radicand < 0:
        raise IntensityInfeasible(
            "target intensity not reachable: known segments alone already "
            "exceed the target NP (required work power^4 is negative)"
        )
    return radicand ** 0.25


def _session_tss_at(x: float, work: list[_WorkStep],
                    known: list[tssmod.Segment]) -> float:
    """Whole-session TSS if the primary dominant intensity were x (ratios
    preserved) — used for the 'closest achievable' figure in reports."""
    ref = work[0].mid_frac
    segs = list(known) + [
        tssmod.Segment(w.seconds_total, (w.mid_frac / ref) * x) for w in work
    ]
    return tssmod.session_tss(segs)


def resolve_proposal_intensity(proposal: dict, *, mode: str,
                               dominant_zone: str,
                               np_target_frac: float,
                               structure_segments: list[tssmod.Segment]) -> dict:
    """Return a COPY of the proposal with the dominant work steps' percent
    ranges replaced by the deterministically solved intensity (spec 16.2).

    `structure_segments` are the effective warmup/prep/cooldown segments
    (durations and midpoint fractions the builder will actually use), so the
    solve accounts for the full session exactly as it will be assembled.

    Power mode only. Raises IntensityInfeasible per spec 16.3.
    """
    if mode != "power":
        raise ValueError("intensity resolution is power-mode only")

    work, known_main = _classify(proposal, dominant_zone)
    known = list(structure_segments) + known_main
    if not work:
        raise IntensityInfeasible("no dominant work steps to resolve")

    x = solve_dominant_intensity(work=work, known=known,
                                 np_target_frac=np_target_frac)

    zone = zone_by_name(mode, dominant_zone)
    ref = work[0].mid_frac

    # Infeasibility check (spec 16.3): EVERY resolved dominant midpoint must
    # sit inside the dominant zone. Report with the closest achievable TSS.
    resolved_mids_pct = [(w.mid_frac / ref) * x * 100.0 for w in work]
    for mid_pct in resolved_mids_pct:
        if not zone.contains(mid_pct):
            # Closest achievable: primary intensity at the violated zone edge
            # (scaled back through the same ratio), keeping structure fixed.
            worst_ratio = max(w.mid_frac / ref for w in work)
            if zone.high_pct is not None and mid_pct >= zone.high_pct:
                x_edge = (zone.high_pct / 100.0) / worst_ratio
            else:
                min_ratio = min(w.mid_frac / ref for w in work)
                x_edge = (zone.low_pct / 100.0) / min_ratio if min_ratio > 0 else 0.0
            achievable = _session_tss_at(x_edge, work, known) if x_edge > 0 else 0.0
            raise IntensityInfeasible(
                f"resolved work intensity {mid_pct:.1f}% falls outside the "
                f"{dominant_zone} zone bounds [{zone.low_pct}"
                f"-{zone.high_pct if zone.high_pct is not None else 'open'}%] "
                f"for this structure; the closest achievable session TSS at "
                f"the zone edge is ~{achievable:.0f}. Adjust the TSS/IF "
                f"target, the duration, or the structure."
            )

    # Rounding (spec 16.4): integer center; keep the proposed width, shrunk
    # symmetrically only as needed to stay inside the zone.
    adjusted = copy.deepcopy(proposal)
    idx = 0
    for st, _occ in _iter_main_steps(adjusted):
        zname = st.get("zone_name", dominant_zone)
        if (not st.get("is_recovery")) and zname == dominant_zone:
            center = int(round(resolved_mids_pct[idx]))
            proposed_hw = work[idx].half_width_pct
            max_hw = float(center - zone.low_pct)
            if zone.high_pct is not None:
                max_hw = min(max_hw, float(zone.high_pct - center))
            hw = int(max(0.0, min(proposed_hw, max_hw)))
            st["low_pct"] = center - hw
            st["high_pct"] = center + hw
            idx += 1
    return adjusted
