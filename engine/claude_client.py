"""
claude_client.py — The Claude reasoning layer (spec Section 9).

Calls the Anthropic Messages API from Python via the official `anthropic` SDK,
with the propose_workout tool (forced tool-use) and optional web search, then
returns Claude's structured proposal as a dict.

Design for testability: the actual API call goes through a `transport`
callable. In production this is the real SDK; in tests it's a mock that
returns a canned proposal — so the whole integration is verifiable here
without an API key or network access. The PRODUCTION transport is provided by
`anthropic_transport()`; it is only constructed when actually used.
"""

from __future__ import annotations
import json
from typing import Callable, Optional

from .proposal import PROPOSAL_TOOL_SCHEMA
from .catalog import CatalogEntry

# A transport takes (system_prompt, user_prompt, tools, use_web_search) and
# returns the tool-input dict that Claude produced for propose_workout.
Transport = Callable[[str, str, list, bool], dict]

MODEL = "claude-sonnet-4-6"  # per spec product info; adjustable


# --- Prompt construction ----------------------------------------------------

def build_system_prompt() -> str:
    return (
        "You are the reasoning core of an indoor cycling workout generator. "
        "You design the STRUCTURE of one workout's main set (and, in HR mode, "
        "the warmup staircase). You are an expert who reasons from exercise "
        "physiology and methodology — never from a fixed menu. Your decisions "
        "must respect these hard rules:\n"
        "- The requested zone is the DOMINANT stimulus (most work time-in-zone). "
        "Any complementary stimuli are SUBORDINATE and must not displace it.\n"
        "- All intensities are integer percent ranges that sit within their "
        "named zone's bounds. Never mix the power and HR zone systems.\n"
        "- Repeat blocks are never nested.\n"
        "- Do NOT compute TSS/IF and do NOT write intervals.icu syntax — return "
        "structural intent only via the propose_workout tool; the engine renders "
        "and does the math.\n"
        "- Vary structure to avoid monotony, but honor every parameter the user "
        "fixed. Use the provided recent-history context to avoid handing back an "
        "effectively identical session, and to progress naturally when relevant."
    )


def build_user_prompt(*, mode: str, zone: str,
                      target_duration_seconds: Optional[int],
                      target_tss: Optional[float],
                      target_if: Optional[float],
                      recent: list[CatalogEntry]) -> str:
    lines = [
        f"Mode: {mode}",
        f"Requested dominant zone: {zone}",
    ]
    if target_duration_seconds:
        lines.append(f"Target total duration: {target_duration_seconds//60} min")
    if target_tss is not None:
        lines.append(f"Target TSS: {target_tss:g}")
    if target_if is not None:
        lines.append(f"Target IF: {target_if:g}")
    if mode == "hr":
        lines.append("HR mode: warmup must be ASCENDING STEPS (a staircase), "
                     "not a ramp. Provide hr_warmup_staircase as ascending "
                     "[low%,high%,seconds] steps totaling <=10 min.")
    if recent:
        lines.append("\nRecent sessions you have generated (context — reason "
                     "over these to add variety / progress naturally; do not "
                     "mechanically avoid, reason):")
        for e in recent[:10]:
            lines.append(f"  - {e.generated_at[:10]} {e.mode}/{e.dominant_zone}: "
                         f"{e.summary}")
    lines.append("\nReturn one propose_workout tool call with your structural "
                 "design for the main set.")
    return "\n".join(lines)


# --- Production transport (real SDK) ----------------------------------------

def anthropic_transport(api_key: Optional[str] = None,
                        use_web_search: bool = False) -> Transport:
    """Build a real transport backed by the anthropic SDK. Imported lazily so
    the module loads (and tests run) without the SDK installed."""
    from anthropic import Anthropic  # lazy import

    client = Anthropic(api_key=api_key) if api_key else Anthropic()

    def _transport(system_prompt: str, user_prompt: str,
                   tools: list, web_search: bool) -> dict:
        request_tools = list(tools)
        # The first non-web tool is the one we force (propose_workout or
        # propose_progression).
        forced = next((t["name"] for t in tools if "name" in t), None)
        if web_search:
            request_tools.append({"type": "web_search_20250305",
                                   "name": "web_search"})
        resp = client.messages.create(
            model=MODEL,
            max_tokens=4000,
            system=system_prompt,
            tools=request_tools,
            tool_choice={"type": "tool", "name": forced} if forced else {"type": "auto"},
            messages=[{"role": "user", "content": user_prompt}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == forced:
                return dict(block.input)
        raise RuntimeError(f"Claude did not return a {forced} tool call")

    return _transport


# --- The reasoning call ------------------------------------------------------

def request_proposal(*, transport: Transport, mode: str, zone: str,
                     target_duration_seconds: Optional[int] = None,
                     target_tss: Optional[float] = None,
                     target_if: Optional[float] = None,
                     recent: Optional[list[CatalogEntry]] = None,
                     use_web_search: bool = False) -> dict:
    """Ask the reasoning layer for a structural proposal. Returns the raw
    proposal dict (still to be validated by proposal.validate_proposal)."""
    system = build_system_prompt()
    user = build_user_prompt(
        mode=mode, zone=zone,
        target_duration_seconds=target_duration_seconds,
        target_tss=target_tss, target_if=target_if,
        recent=recent or [],
    )
    return transport(system, user, [PROPOSAL_TOOL_SCHEMA], use_web_search)


def request_progression(*, transport: Transport, mode: str, zone: str,
                        initial_session_seconds: Optional[int] = None,
                        max_session_seconds: Optional[int] = None,
                        recent: Optional[list[CatalogEntry]] = None,
                        use_web_search: bool = False) -> dict:
    """Ask the reasoning layer for a full reasoned progression (Section 15).
    Returns the raw progression dict (validate with validate_progression).

    The prompt imposes NO methodology (no 'progress volume', no 'alternate
    continuous/interval', no single author's recipe). The ONLY floor is that
    the sequence be coherent and directional. How it progresses, and the
    physiological ceiling, are the engine's to reason and research live."""
    from .progression import PROGRESSION_TOOL_SCHEMA  # local import avoids cycle
    system = build_system_prompt()
    lines = [
        f"Mode: {mode}",
        f"Requested progression for dominant stimulus: {zone}",
        "",
        "Design a progression: an ordered sequence of sessions that forms a "
        "COHERENT sequence WITH DIRECTION — each session a sensible step toward "
        "the progression's endpoint, never random disconnected sessions. That "
        "coherent direction is the only fixed requirement. HOW it progresses "
        "(volume, density, structure, recovery, etc.) is yours to reason from "
        "physiology and methodology — investigate live as needed. Do not follow "
        "any single author's recipe; reason your own appropriate progression.",
    ]
    if initial_session_seconds:
        lines.append(
            f"\nDay 1 session budget: {initial_session_seconds//60} min TOTAL "
            f"(including warmup/cooldown). Size warmup/cooldown to the budget — "
            f"do not waste time on a long warmup in a short session.")
    if max_session_seconds:
        # Case B: start + max given
        lines.append(
            f"Maximum session duration: {max_session_seconds//60} min. Develop "
            f"the ideal load between the starting budget and this maximum.")
    else:
        # Case A: only initial given -> engine researches the ceiling
        lines.append(
            "No maximum was given. Grow the progression up to the PHYSIOLOGICAL "
            "CEILING of this stimulus, which you should determine by live "
            "research (e.g. how many minutes in-zone it makes sense to progress "
            "to). When the ceiling is reached, add a graduation_note for the "
            "next stimulus.")
    if mode == "hr":
        lines.append("HR mode: each session's warmup is an ascending STAIRCASE "
                     "(hr_warmup_staircase), never a ramp.")
    if recent:
        lines.append("\nYour own catalog of recent sessions (your memory/"
                     "library — reuse/adapt your prior reasoning, don't reinvent "
                     "the wheel; this is your own work, not an external recipe):")
        for e in recent[:10]:
            lines.append(f"  - {e.dominant_zone}: {e.summary}")
    lines.append("\nReturn one propose_progression tool call.")
    user = "\n".join(lines)
    return transport(system, user, [PROGRESSION_TOOL_SCHEMA], use_web_search)
