"""
request_parser.py — Natural-language request interpretation.

Turns a plain sentence — in SPANISH or ENGLISH — ("resistencia aerobica de 1
hora" / "aerobic endurance for 1 hour", "una progresion de tempo empezando en
30 min por frecuencia cardiaca" / "a tempo progression starting at 30 min by
heart rate") into the structured parameters the engine needs. Claude does the
interpretation — including mapping the user's plain wording (in either
language) to the correct technical zone name in the correct system (power vs
HR), which the user never has to know.

The two zone systems are never mixed: the parser picks power OR hr, then the
zone name from that system only. The detected input language is also
returned, so the calling front-end (pedir.py) can mirror it in its own status
messages.
"""

from __future__ import annotations
import json
from typing import Callable, Optional

# Reuse the same injectable transport idea as claude_client, but this call
# uses a different tool (parse_request). We build a dedicated transport here
# so parsing is testable with a mock too.

PARSE_TOOL_SCHEMA = {
    "name": "parse_request",
    "description": (
        "Interpret a natural-language cycling-workout request — written in "
        "EITHER Spanish or English — into structured parameters. Map the "
        "user's plain wording, in whichever language they used, to the "
        "correct technical zone name in the correct system. The POWER system "
        "zones are: ActiveRecovery, Endurance, Tempo, SweetSpot, Threshold, "
        "VO2Max, Anaerobic, Neuromuscular. The HR system zones are: Recovery, "
        "Aerobic, Tempo, SubThreshold, SuperThreshold, AerobicCapacity, "
        "Anaerobic. Choose the system from how the user asks (power/watts/FTP "
        "-> power; heart rate/pulse/FC/LTHR/pulso -> hr). Default to power if "
        "unspecified. Never mix systems.\n"
        "Bilingual zone-wording examples (ES / EN):\n"
        "  - 'recuperacion activa' / 'active recovery' -> ActiveRecovery\n"
        "  - 'resistencia aerobica' / 'aerobic endurance', 'base' / 'base "
        "miles' -> Endurance (power) or Aerobic (hr)\n"
        "  - 'tempo' / 'tempo' -> Tempo (same name both systems)\n"
        "  - 'sweet spot', 'sweetspot' / 'sweet spot' -> SweetSpot\n"
        "  - 'umbral' / 'threshold' -> Threshold (power) or SubThreshold (hr)\n"
        "  - 'vo2 max', 'vo2max' / 'vo2 max' -> VO2Max (power) or "
        "SuperThreshold (hr)\n"
        "  - 'anaerobico' / 'anaerobic' -> Anaerobic (power) or "
        "AerobicCapacity (hr)\n"
        "  - 'neuromuscular', 'sprints' / 'neuromuscular', 'sprints' -> "
        "Neuromuscular (power) or Anaerobic (hr)"
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "mode", "zone", "language"],
        "properties": {
            "kind": {"type": "string", "enum": ["single_session", "progression"]},
            "mode": {"type": "string", "enum": ["power", "hr"]},
            "zone": {"type": "string",
                     "description": "Technical zone name in the chosen system."},
            "language": {
                "type": "string", "enum": ["es", "en"],
                "description": "The language the user wrote their request in "
                               "(Spanish or English), detected from the text.",
            },
            "duration_minutes": {"type": "integer",
                                 "description": "Session duration if given "
                                 "(single session), or Day-1 duration "
                                 "(progression)."},
            "max_duration_minutes": {"type": "integer",
                                     "description": "Max session duration if "
                                     "the user gave an upper bound."},
            "target_tss": {"type": "number"},
            "target_if": {"type": "number"},
            "interpretation_note": {
                "type": "string",
                "description": "One short line restating what you understood, "
                               "for confirmation. MUST be written in the SAME "
                               "language as the user's request (Spanish "
                               "request -> Spanish note; English request -> "
                               "English note).",
            },
        },
    },
}


def parse_request(*, transport: Callable, text: str) -> dict:
    """Interpret a natural-language request (Spanish or English). `transport`
    has the same signature as claude_client.Transport:
    (system, user, tools, web) -> dict."""
    system = (
        "You interpret natural-language indoor cycling workout requests — "
        "written in Spanish OR English — into structured parameters via the "
        "parse_request tool. Detect and report which language was used. Be "
        "faithful to what the user asked; do not invent constraints they "
        "didn't state. If they didn't specify power vs heart rate, default to "
        "power. Map plain wording, in whichever language, to the correct "
        "technical zone name in the correct system. Write interpretation_note "
        "in the same language the user wrote in."
    )
    user = f"Interpret this request:\n\n{text}\n\nReturn one parse_request tool call."
    return transport(system, user, [PARSE_TOOL_SCHEMA], False)


def parse_transport_from_anthropic(api_key: Optional[str] = None) -> Callable:
    """A dedicated transport for parsing (forces the parse_request tool)."""
    from anthropic import Anthropic
    client = Anthropic(api_key=api_key) if api_key else Anthropic()

    def _t(system_prompt: str, user_prompt: str, tools: list, web: bool) -> dict:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=system_prompt,
            tools=tools,
            tool_choice={"type": "tool", "name": "parse_request"},
            messages=[{"role": "user", "content": user_prompt}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "parse_request":
                return dict(block.input)
        raise RuntimeError("parse_request tool call not returned")

    return _t
