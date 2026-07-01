"""
request_parser.py — Natural-language request interpretation.

Turns a plain sentence ("resistencia aerobica de 1 hora", "una progresion de
tempo empezando en 30 min por frecuencia cardiaca") into the structured
parameters the engine needs. Claude does the interpretation — including
mapping the user's plain wording to the correct technical zone name in the
correct system (power vs HR), which the user never has to know.

The two zone systems are never mixed: the parser picks power OR hr, then the
zone name from that system only.
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
        "Interpret a natural-language cycling-workout request into structured "
        "parameters. Map the user's plain wording to the correct technical zone "
        "name in the correct system. The POWER system zones are: ActiveRecovery, "
        "Endurance, Tempo, SweetSpot, Threshold, VO2Max, Anaerobic, "
        "Neuromuscular. The HR system zones are: Recovery, Aerobic, Tempo, "
        "SubThreshold, SuperThreshold, AerobicCapacity, Anaerobic. Choose the "
        "system from how the user asks (power/watts/FTP -> power; heart rate/"
        "pulse/FC/LTHR -> hr). Default to power if unspecified. Never mix "
        "systems. Examples: 'resistencia aerobica' -> Endurance (power) or "
        "Aerobic (hr); 'umbral' -> Threshold (power) or SubThreshold (hr)."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "mode", "zone"],
        "properties": {
            "kind": {"type": "string", "enum": ["single_session", "progression"]},
            "mode": {"type": "string", "enum": ["power", "hr"]},
            "zone": {"type": "string",
                     "description": "Technical zone name in the chosen system."},
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
                "description": "One short line, in the user's language, "
                               "restating what you understood (for confirmation).",
            },
        },
    },
}


def parse_request(*, transport: Callable, text: str) -> dict:
    """Interpret a natural-language request. `transport` has the same
    signature as claude_client.Transport: (system, user, tools, web) -> dict."""
    system = (
        "You interpret natural-language indoor cycling workout requests into "
        "structured parameters via the parse_request tool. Be faithful to what "
        "the user asked; do not invent constraints they didn't state. If they "
        "didn't specify power vs heart rate, default to power. Map plain "
        "wording to the correct technical zone name in the correct system."
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
