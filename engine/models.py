"""
models.py — Data structures for requests and generated sessions.
Mirrors the validated JSON schema (workout_engine_schema.json).

These are plain dataclasses for the deterministic core. The Phase-2 Claude
layer will populate the creative fields; Phase-1 fills them with a provisional
placeholder strategy (see structure.py) so the end-to-end flow runs today.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Literal

Mode = Literal["power", "hr"]


# --- Request ----------------------------------------------------------------

@dataclass
class RecoveryWeekReduction:
    reduce_duration_pct: Optional[float] = None
    reduce_session_count_to: Optional[int] = None
    reduce_intensity_note: Optional[str] = None


@dataclass
class ProgressionSpec:
    total_weeks: int
    sessions_per_week: int
    load_to_recovery_ratio: str            # e.g. "3:1"
    recovery_week_reduction: Optional[RecoveryWeekReduction] = None
    load_week_ramp: Optional[str] = None   # absent => engine does NOT ramp


@dataclass
class Athlete:
    # All optional, internal-only, never rendered as absolute watts/bpm.
    cp_watts: Optional[float] = None        # = FTP display label
    w_prime_joules: Optional[float] = None
    lthr_bpm: Optional[float] = None


@dataclass
class GenerationRequest:
    kind: Literal["single_session", "progression"]
    mode: Mode
    requested_zone: Optional[str] = None    # zone name in the chosen system
    target_duration_seconds: Optional[int] = None
    max_available_seconds: Optional[int] = None
    target_tss: Optional[float] = None
    target_if: Optional[float] = None
    athlete: Athlete = field(default_factory=Athlete)
    progression: Optional[ProgressionSpec] = None


# --- Generated session ------------------------------------------------------

@dataclass
class Step:
    role: str                  # warmup_ramp | warmup_prep | work | recovery | cooldown
    duration_seconds: int
    is_ramp: bool = False
    flat_low: Optional[int] = None
    flat_high: Optional[int] = None
    ramp_start: Optional[int] = None
    ramp_end: Optional[int] = None
    cadence_low: Optional[int] = None
    cadence_high: Optional[int] = None
    rpe_low: Optional[int] = None
    rpe_high: Optional[int] = None
    rendering: str = ""


@dataclass
class RepeatBlock:
    repeats: int
    steps: list[Step]


# A section element is either a Step or a RepeatBlock.
SectionElement = object  # documented union; kept loose for the core


@dataclass
class Warmup:
    # Power mode: `ramp` holds the single ascending ramp step, `steps` is None.
    # HR mode: `steps` holds the ascending staircase (list of Steps), `ramp` is None.
    # In both modes `prep` is the flexible (1-2 min) always-present prep block.
    prep: Step
    ramp: Optional[Step] = None
    steps: Optional[list] = None   # list[Step] for HR staircase


@dataclass
class Feasibility:
    satisfied: bool = True
    conflict_report: Optional[str] = None


@dataclass
class GeneratedSession:
    id: str
    generated_at: str
    mode: Mode
    dominant_zone: str
    structural_pattern: Optional[str]
    complementary_zones: list[str]
    warmup: Warmup
    main_set: list                # list[Step | RepeatBlock]
    cooldown: list                # list[Step | RepeatBlock]
    estimated_tss: float
    estimated_if: float
    feasibility: Feasibility
    summary: str
    markdown_output: str
    progression_id: Optional[str] = None
    generation_seed: Optional[int] = None
