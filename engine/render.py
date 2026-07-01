"""
render.py — Compile workout steps into literal intervals.icu syntax
(spec Section 12.2), with rounding (spec 16.4) and the mandatory
output-validation gate (spec 12.3).

Grammar (spec 12.2):  [duration] [target] [optional cadence] [RPE]
  - duration: time-based only (Xh Ym Zs). NEVER distance (mtr/km forbidden).
  - power target: bare "low-high%"  (no "FTP" word).
  - HR target:    "low-high% LTHR"  (never "% HR" — that is max-HR relative).
  - ramp:         "ramp start-end%" (+ "LTHR" for HR mode).
  - cadence:      "low-highrpm" or "Nrpm".
  - RPE:          "[RPE low-high]"  (bracket attached, per the syntax file).

The output-validation gate REJECTS any line containing out-of-scope constructs
(distance, freeride, "% HR", "% Pace") before anything is written/exported.
"""

from __future__ import annotations
import re


# --- Duration formatting ----------------------------------------------------

def format_duration(total_seconds: int) -> str:
    """Format integer seconds as intervals.icu duration (e.g. 90 -> '1m30s',
    600 -> '10m', 3661 -> '1h1m1s'). Rounding to whole seconds is assumed to
    have already happened (spec 16.4)."""
    if total_seconds <= 0:
        raise ValueError(f"duration must be positive, got {total_seconds}")
    s = int(round(total_seconds))
    if s <= 0:
        raise ValueError(
            f"duration rounds to {s}s (from {total_seconds}s) — too short to "
            f"render; every step must be at least 1 second"
        )
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    out = ""
    if h:
        out += f"{h}h"
    if m:
        out += f"{m}m"
    if sec:
        out += f"{sec}s"
    return out


# --- Target formatting ------------------------------------------------------

def _mode_suffix(mode: str) -> str:
    """Suffix appended to a percent target. Power = none; HR = ' LTHR'."""
    if mode == "power":
        return "%"
    if mode == "hr":
        return "% LTHR"
    raise ValueError(f"unknown mode: {mode!r}")


def format_flat_target(mode: str, low_pct: int, high_pct: int) -> str:
    lo, hi = int(round(low_pct)), int(round(high_pct))
    if lo == hi:
        return f"{lo}{_mode_suffix(mode)}"
    return f"{lo}-{hi}{_mode_suffix(mode)}"


def format_ramp_target(mode: str, start_pct: int, end_pct: int) -> str:
    a, b = int(round(start_pct)), int(round(end_pct))
    return f"ramp {a}-{b}{_mode_suffix(mode)}"


def format_cadence(low_rpm: int, high_rpm: int) -> str:
    lo, hi = int(round(low_rpm)), int(round(high_rpm))
    if lo == hi:
        return f"{lo}rpm"
    return f"{lo}-{hi}rpm"


def format_rpe(low: int, high: int) -> str:
    return f"[RPE {int(low)}-{int(high)}]"


# --- Step line assembly -----------------------------------------------------

def render_step_line(
    *,
    mode: str,
    duration_seconds: int,
    is_ramp: bool = False,
    flat_low: int | None = None,
    flat_high: int | None = None,
    ramp_start: int | None = None,
    ramp_end: int | None = None,
    cadence_low: int | None = None,
    cadence_high: int | None = None,
    rpe_low: int | None = None,
    rpe_high: int | None = None,
) -> str:
    """Assemble one '- duration target [cadence] [RPE]' line."""
    parts = [format_duration(duration_seconds)]

    if is_ramp:
        if ramp_start is None or ramp_end is None:
            raise ValueError("ramp step requires ramp_start and ramp_end")
        parts.append(format_ramp_target(mode, ramp_start, ramp_end))
    else:
        if flat_low is None or flat_high is None:
            raise ValueError("flat step requires flat_low and flat_high")
        parts.append(format_flat_target(mode, flat_low, flat_high))

    if cadence_low is not None and cadence_high is not None:
        parts.append(format_cadence(cadence_low, cadence_high))

    if rpe_low is not None and rpe_high is not None:
        parts.append(format_rpe(rpe_low, rpe_high))

    return "- " + " ".join(parts)


# --- Output validation gate (spec 12.3) -------------------------------------

# Forbidden constructs. The grammar permits these, so "the spec says not to" is
# not enough — we actively reject them before export.
_FORBIDDEN_PATTERNS = {
    "distance (mtr)": re.compile(r"\d+\s*mtr\b", re.IGNORECASE),
    "distance (km)": re.compile(r"\d+\s*km\b", re.IGNORECASE),
    "freeride": re.compile(r"\bfreeride\b", re.IGNORECASE),
    "max-HR percent (% HR)": re.compile(r"%\s*HR\b"),  # must be % LTHR
    "pace target": re.compile(r"%\s*Pace\b", re.IGNORECASE),
}


class OutputValidationError(ValueError):
    """Raised when generated output contains an out-of-scope construct."""


def validate_output(text: str) -> None:
    """Reject any out-of-scope construct anywhere in the rendered output.
    Raises OutputValidationError on the first violation found."""
    for label, pattern in _FORBIDDEN_PATTERNS.items():
        m = pattern.search(text)
        if m:
            raise OutputValidationError(
                f"forbidden construct {label!r} found in output: {m.group(0)!r}"
            )
