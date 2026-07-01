"""
progression.py — Reasoned multi-session progressions (spec Section 15) under
the free-reasoning / no-KB rule (Section 9.6).

The user asks for e.g. "a Tempo progression." The engine REASONS the whole
sequence of sessions — each progressing (typically in volume, letting power
progress on its own, not driven up), alternating structure, up to the
stimulus's physiological ceiling — and then, when that ceiling is reached,
may note it's time to graduate to the next stimulus. This is reasoned live,
never copied from a cached template.

Claude returns the progression as an ordered list of per-session structural
proposals (same shape as a single-session proposal). Python validates each,
then builds/renders each with the deterministic core.
"""

from __future__ import annotations
from .proposal import PROPOSAL_TOOL_SCHEMA, validate_proposal, ProposalRejected


# Tool schema: a progression is an ordered list of session proposals plus a
# short reasoning note. Each session reuses the single-session proposal shape.
PROGRESSION_TOOL_SCHEMA = {
    "name": "propose_progression",
    "description": (
        "Propose a progression for the requested dominant stimulus: an ordered "
        "sequence of sessions that forms a COHERENT sequence WITH DIRECTION "
        "(each session a sensible step toward the endpoint; never random "
        "disconnected sessions). That coherent direction is the only fixed "
        "requirement. HOW it progresses is yours to reason from physiology and "
        "methodology — investigate live as needed; do not copy any single "
        "author's recipe. Size each session's warmup/cooldown to its time "
        "budget. Each session is a structural proposal (same shape as "
        "propose_workout). Do NOT compute TSS/IF or write intervals.icu "
        "syntax — the engine renders and does the math."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["sessions", "reasoning"],
        "properties": {
            "reasoning": {
                "type": "string",
                "description": "Brief explanation of the progression logic "
                               "(why this sequence, what progresses, the ceiling).",
            },
            "graduation_note": {
                "type": "string",
                "description": "Optional: if the sequence reaches the stimulus "
                               "ceiling, what stimulus to graduate to next and why.",
            },
            "sessions": {
                "type": "array",
                "minItems": 1,
                "items": PROPOSAL_TOOL_SCHEMA["input_schema"],
            },
        },
    },
}


def validate_progression(progression: dict, *, mode: str,
                         dominant_zone: str,
                         session_budgets: list[int | None] | None = None) -> None:
    """Validate every session in the progression against the same hard rules
    as a single session, including per-session budget conservation (spec 15).
    `session_budgets`, if given, is a list the same length as `sessions`,
    each entry the time budget (seconds) that session must fit within
    (None = no budget check for that session)."""
    sessions = progression.get("sessions")
    if not sessions:
        raise ProposalRejected("progression has no sessions")
    for i, sess in enumerate(sessions):
        budget = session_budgets[i] if session_budgets and i < len(session_budgets) else None
        try:
            validate_proposal(sess, mode=mode, dominant_zone=dominant_zone,
                              total_budget_seconds=budget)
        except ProposalRejected as e:
            raise ProposalRejected(f"session {i+1} invalid: {e}")
