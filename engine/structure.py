"""
structure.py — Mandatory session structure (spec Section 11) and the
provisional Phase-1 main-set logic.

Every session ALWAYS has: Warmup (ascending ramp + fixed 2m 45-55% prep)
+ Main Set + Cooldown (descending ramp OR fixed easy interval).

================================ IMPORTANT ================================
The main-set SHAPE decisions here (how many reps, how long, what complementary
stimuli) are PROVISIONAL PHASE-1 PLACEHOLDERS. They exist only so the
end-to-end flow runs and is testable today. They are intentionally simple and
will be REPLACED WHOLESALE by the Phase-2 Claude reasoning layer, which will
reason from physiology/methodology + the catalog + web search.
Do NOT mistake this placeholder for the engine's real intelligence.
==========================================================================
"""

from __future__ import annotations
from .models import Step, RepeatBlock, Warmup
from .rpe import rpe_for_flat, rpe_for_ramp
from .render import render_step_line
from . import tss as tssmod


# --- Mandatory warmup / cooldown (spec 11) ----------------------------------

# The prep block differs by mode (spec 11.1) and its DURATION is flexible
# between 1 and 2 minutes (engine-reasoned), but the block is ALWAYS present.
PREP_LOW, PREP_HIGH = 45, 55            # power-mode prep
PREP_LOW_HR, PREP_HIGH_HR = 60, 80     # HR-mode prep
PREP_MIN_SECONDS, PREP_MAX_SECONDS = 60, 120
WARMUP_RAMP_MAX = 600   # 10 min CAP (not a target); engine sizes to budget
COOLDOWN_MAX = 300      # 5 min CAP (not a target)


def _clamp_prep(seconds: int) -> int:
    return max(PREP_MIN_SECONDS, min(PREP_MAX_SECONDS, seconds))


def _prep_bounds(mode: str) -> tuple[int, int]:
    return (PREP_LOW_HR, PREP_HIGH_HR) if mode == "hr" else (PREP_LOW, PREP_HIGH)


def build_warmup(mode: str, ramp_start: int, ramp_end: int,
                 ramp_seconds: int = WARMUP_RAMP_MAX,
                 prep_seconds: int = PREP_MAX_SECONDS) -> Warmup:
    """POWER mode: ascending ramp (engine-sized duration, capped at 10 min) +
    flexible prep (1-2 min, always present). (HR uses build_warmup_hr_staircase.)"""
    ramp_seconds = min(ramp_seconds, WARMUP_RAMP_MAX)
    r_lo, r_hi = rpe_for_ramp(mode, ramp_start, ramp_end)
    ramp = Step(
        role="warmup_ramp", duration_seconds=ramp_seconds, is_ramp=True,
        ramp_start=ramp_start, ramp_end=ramp_end, rpe_low=r_lo, rpe_high=r_hi,
        rendering=render_step_line(
            mode=mode, duration_seconds=ramp_seconds, is_ramp=True,
            ramp_start=ramp_start, ramp_end=ramp_end, rpe_low=r_lo, rpe_high=r_hi,
        ),
    )
    prep = _build_prep(mode, prep_seconds)
    return Warmup(ramp=ramp, prep=prep)


def _build_prep(mode: str, seconds: int = PREP_MAX_SECONDS) -> Step:
    """The single always-present prep block, mode-dependent (spec 11.1),
    flexible 1-2 min."""
    seconds = _clamp_prep(seconds)
    lo, hi = _prep_bounds(mode)
    p_lo, p_hi = rpe_for_flat(mode, lo, hi)
    return Step(
        role="warmup_prep", duration_seconds=seconds,
        flat_low=lo, flat_high=hi, rpe_low=p_lo, rpe_high=p_hi,
        rendering=render_step_line(
            mode=mode, duration_seconds=seconds,
            flat_low=lo, flat_high=hi, rpe_low=p_lo, rpe_high=p_hi,
        ),
    )


def build_warmup_hr_staircase(steps: list[tuple[int, int, int]],
                              prep_seconds: int = PREP_MAX_SECONDS) -> Warmup:
    """HR mode: ascending progressive STEPS (a staircase), not a ramp (spec
    11.1) — HR can't follow a smooth ramp. Each step is (low%, high%, seconds).
    The number of steps and their %s are engine-determined (NOT fixed). The
    fixed 2m 60-80% LTHR prep block follows. Total stepped portion <= 10 min."""
    total = sum(s[2] for s in steps)
    if total > WARMUP_RAMP_MAX:
        raise ValueError(f"HR warmup staircase {total}s exceeds 10min limit")
    rendered_steps: list[Step] = []
    for (lo, hi, secs) in steps:
        r_lo, r_hi = rpe_for_flat("hr", lo, hi)
        rendered_steps.append(Step(
            role="warmup_ramp", duration_seconds=secs,
            flat_low=lo, flat_high=hi, rpe_low=r_lo, rpe_high=r_hi,
            rendering=render_step_line(
                mode="hr", duration_seconds=secs,
                flat_low=lo, flat_high=hi, rpe_low=r_lo, rpe_high=r_hi,
            ),
        ))
    prep = _build_prep("hr", prep_seconds)
    return Warmup(ramp=None, steps=rendered_steps, prep=prep)


def build_cooldown_hr_single(low: int, high: int, seconds: int = COOLDOWN_MAX) -> list:
    """HR mode: fewest steps possible — a single recovery block (spec 11.3).
    No descending ramp. % LTHR engine-determined; <= 5 min."""
    seconds = min(seconds, COOLDOWN_MAX)
    lo, hi = rpe_for_flat("hr", low, high)
    step = Step(
        role="cooldown", duration_seconds=seconds,
        flat_low=low, flat_high=high, rpe_low=lo, rpe_high=hi,
        rendering=render_step_line(
            mode="hr", duration_seconds=seconds,
            flat_low=low, flat_high=high, rpe_low=lo, rpe_high=hi,
        ),
    )
    return [step]


def build_cooldown_ramp(mode: str, start: int, end: int,
                        seconds: int = COOLDOWN_MAX) -> list:
    """Form A: descending ramp (direction fixed; % engine-determined)."""
    seconds = min(seconds, COOLDOWN_MAX)
    lo, hi = rpe_for_ramp(mode, start, end)
    step = Step(
        role="cooldown", duration_seconds=seconds, is_ramp=True,
        ramp_start=start, ramp_end=end, rpe_low=lo, rpe_high=hi,
        rendering=render_step_line(
            mode=mode, duration_seconds=seconds, is_ramp=True,
            ramp_start=start, ramp_end=end, rpe_low=lo, rpe_high=hi,
        ),
    )
    return [step]


# --- Hard-constraint conflict detection (spec 16.3) -------------------------

class ConstraintConflict(Exception):
    """Raised when target TSS/IF and max duration cannot both hold."""
    def __init__(self, report: str):
        super().__init__(report)
        self.report = report


def check_duration_vs_tss(target_tss: float | None, target_if: float | None,
                          max_available_seconds: int | None) -> None:
    """If a target TSS at a given IF needs more time than is available, report
    the conflict with numbers — never silently pick which to sacrifice."""
    if target_tss is None or target_if is None or max_available_seconds is None:
        return
    needed = tssmod.duration_from(target_tss, target_if)
    if needed > max_available_seconds:
        max_tss = tssmod.tss_from(max_available_seconds, target_if)
        raise ConstraintConflict(
            f"TSS {target_tss:g} at IF {target_if:g} needs "
            f"{needed/60:.1f} min, but max available is "
            f"{max_available_seconds/60:.1f} min. "
            f"Highest TSS achievable in that time at this IF is {max_tss:.0f}."
        )


# --- PROVISIONAL Phase-1 main-set placeholder -------------------------------

def provisional_main_set(mode: str, zone_low: int, zone_high: int,
                         work_seconds_each: int, reps: int,
                         recovery_low: int, recovery_high: int,
                         recovery_seconds: int) -> RepeatBlock:
    """[PHASE-1 PLACEHOLDER] A plain Nx(work/recovery) block. Dumb on purpose.
    Phase 2 replaces this with reasoned, varied, catalog-aware structure."""
    w_lo, w_hi = rpe_for_flat(mode, zone_low, zone_high)
    rc_lo, rc_hi = rpe_for_flat(mode, recovery_low, recovery_high)
    work = Step(
        role="work", duration_seconds=work_seconds_each,
        flat_low=zone_low, flat_high=zone_high, rpe_low=w_lo, rpe_high=w_hi,
        rendering=render_step_line(
            mode=mode, duration_seconds=work_seconds_each,
            flat_low=zone_low, flat_high=zone_high, rpe_low=w_lo, rpe_high=w_hi,
        ),
    )
    recovery = Step(
        role="recovery", duration_seconds=recovery_seconds,
        flat_low=recovery_low, flat_high=recovery_high,
        rpe_low=rc_lo, rpe_high=rc_hi,
        rendering=render_step_line(
            mode=mode, duration_seconds=recovery_seconds,
            flat_low=recovery_low, flat_high=recovery_high,
            rpe_low=rc_lo, rpe_high=rc_hi,
        ),
    )
    return RepeatBlock(repeats=reps, steps=[work, recovery])
