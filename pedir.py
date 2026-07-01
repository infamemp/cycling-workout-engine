"""
pedir.py — Natural-language workout request (front-end command).

Usage (from the workout_engine folder):
    python pedir.py "entrenamiento de resistencia aerobica de 1 hora"
    python pedir.py "una progresion de tempo empezando en 30 minutos"
    python pedir.py "vo2 max de 45 min por frecuencia cardiaca"

You write the request in plain language. Claude interprets it (zone, duration,
power vs HR, single session vs progression), then the engine generates a real,
validated intervals.icu workout. The result is printed and saved to a .md file.
"""

from __future__ import annotations
import sys
import os

from engine.request_parser import parse_request, parse_transport_from_anthropic
from engine.claude_client import anthropic_transport
from engine.generator_v2 import generate_single_v2
from engine.generate_progression import generate_progression
from engine.models import GenerationRequest
from engine.catalog import Catalog


CATALOG_FILE = "my_catalog.sqlite"


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print('Uso: python pedir.py "tu peticion en lenguaje normal"')
        print('Ejemplos:')
        print('  python pedir.py "resistencia aerobica de 1 hora"')
        print('  python pedir.py "una progresion de tempo empezando en 30 minutos"')
        print('  python pedir.py "vo2 max 45 min por frecuencia cardiaca"')
        return 1

    text = " ".join(sys.argv[1:]).strip()

    # 1) Interpret the natural-language request.
    print("Interpretando tu peticion...")
    parse_t = parse_transport_from_anthropic()
    try:
        parsed = parse_request(transport=parse_t, text=text)
    except Exception as e:
        print(f"No pude interpretar la peticion: {e}")
        return 2

    note = parsed.get("interpretation_note", "")
    if note:
        print(f"  Entendi: {note}")
    print(f"  -> modo={parsed['mode']}, zona={parsed['zone']}, "
          f"tipo={parsed['kind']}")
    print()

    # 2) Build the structured request.
    dur_min = parsed.get("duration_minutes")
    maxd_min = parsed.get("max_duration_minutes")
    req = GenerationRequest(
        kind=parsed["kind"],
        mode=parsed["mode"],
        requested_zone=parsed["zone"],
        target_duration_seconds=dur_min * 60 if dur_min else None,
        max_available_seconds=maxd_min * 60 if maxd_min else None,
        target_tss=parsed.get("target_tss"),
        target_if=parsed.get("target_if"),
    )

    catalog = Catalog(CATALOG_FILE)
    gen_t = anthropic_transport(use_web_search=True)

    # 3) Generate (single session or full progression).
    print("Generando... (Claude esta razonando)")
    print()
    try:
        if parsed["kind"] == "progression":
            result = generate_progression(
                req, transport=gen_t, catalog=catalog, use_web_search=True,
                initial_session_seconds=req.target_duration_seconds,
            )
            _show_progression(result)
        else:
            sess = generate_single_v2(
                req, transport=gen_t, catalog=catalog, use_web_search=True,
            )
            _show_session(sess)
    except Exception as e:
        print(f"Error al generar: {e}")
        catalog.close()
        return 3

    catalog.close()
    return 0


def _show_session(sess) -> None:
    print(sess.markdown_output)
    print(f"\nTSS estimado: {sess.estimated_tss}  |  IF: {sess.estimated_if}")
    fname = f"workout_{sess.id}.md"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(sess.markdown_output)
    print(f"Guardado en: {fname}")


def _show_progression(result) -> None:
    print(f"PROGRESION ({len(result.sessions)} sesiones)")
    print(f"Razonamiento: {result.reasoning}")
    if result.graduation_note:
        print(f"Graduacion: {result.graduation_note}")
    print()
    folder = f"progression_{result.progression_id}"
    os.makedirs(folder, exist_ok=True)
    for i, sess in enumerate(result.sessions, start=1):
        print(f"--- Sesion {i}/{len(result.sessions)}  "
              f"(TSS {sess.estimated_tss}) ---")
        print(sess.markdown_output)
        print()
        fname = os.path.join(folder, f"session_{i:02d}.md")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(sess.markdown_output)
    print(f"Todas las sesiones guardadas en la carpeta: {folder}")


if __name__ == "__main__":
    raise SystemExit(main())
