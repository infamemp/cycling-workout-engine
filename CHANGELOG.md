# Cycling Workout Generator — CHANGELOG & Restore Point

**Restore point date:** 2026-06-30 (updated: post-cleanup pass)
**Status:** Specification v2.3 · Engine: Phase 1 + Phase 2 + Progressions + Natural-language front-end · 48 tests passing · Bug cleanup pass complete

---

## 0. Cleanup pass (latest session)

A full module-by-module review found and fixed:

- 🔴 **Critical (fixed):** `generate_progression.py` never applied the budget-aware
  warmup/prep/cooldown sizing or budget validation that `generator_v2.py` got
  earlier — every progression session silently used the max 10/2/5-min
  structure regardless of the user's stated time budget (e.g. a 30-min Day-1
  request). Now fixed: per-session budgets computed (Day 1 = initial budget;
  later sessions = user's max, if given), Claude-proposed structure durations
  used, budget conservation enforced identically to single sessions.
- 🟠 **Important (fixed):** a requested `target_tss`/`target_if` was never
  verified against what was actually built — `solve_work_power_frac` existed
  but was never called. Added `verify_tss_target()` (±10% tolerance) into the
  generation retry loop; a proposal whose real TSS deviates too much is now
  rejected and retried, never silently accepted.
- 🟡 Minor fixes: stale docstring in `models.py`; zone name now validated
  locally before spending API retries (fail fast); `format_duration` guards
  against a theoretical empty-duration render; `complementary_stimuli`
  metadata must now match what's actually used in `main_set` (metadata
  honesty check).
- Added: `pedir.py` (natural-language front-end command) + `request_parser.py`
  (Claude-based interpretation of plain-language requests into structured
  parameters — user never needs to know internal zone names).
- Test count: 43 → 48 (6 new regression tests covering all fixes above).

---

This document is a single-glance snapshot of where the project stands: every
locked decision, the architecture, what's built, what's tested, and what
remains. Use it to resume cleanly without re-reading the whole conversation.

---

## 1. Project in one paragraph

A **standalone, local** Python engine that generates **indoor cycling workouts**
(single sessions and reasoned multi-session progressions) as **intervals.icu
syntax** (`.md` files). Output is always **percentage-based** (`%` of FTP for
power, `% LTHR` for HR) with **RPE ranges**. The engine's intelligence comes
from a **Claude reasoning layer** (creativity, structure, progression logic)
sitting on top of a **deterministic Python core** (math, rendering, validation,
catalog). It is independent of all other projects (not tied to the existing
coach prompt or zone KBs).

---

## 2. Locked decisions (the spine of the project)

### Identity & philosophy
- **The engine reasons; it does not pick from a menu.** No fixed recipe tables.
- **NO pre-loaded knowledge base, ever** (spec §9.6). A KB degenerates into a
  template and makes the engine lazy. Reasoning = free reasoning + **live web
  search** only. Web search is kept; a static KB is forbidden.
- **The engine obeys; it is not a coach.** It generates what's asked. It never
  decides *when/whether* to apply training, athlete readiness, periodization
  shape — those belong to a separate coach. Incomplete requests are flagged,
  never silently filled.
- **Governing split:** training-methodology decisions are engine-reasoned (or
  user-specified), never defaulted by code; purely mechanical/arithmetic
  decisions (TSS math, budget conservation, rendering, catalog) are the core's.

### Zones (spec §4)
- **Friel preset zones**, used **natively and independently**. Power (%FTP) and
  HR (%LTHR) are **never cross-correlated** — same zone names (e.g. "Tempo")
  are different systems. Power is primary/default; HR is secondary.
- Friel zone boundaries are **unmodified** — naming-only relationship to CP.

### CP / W′ (spec §7)
- Physiological foundation is **CP/W′**; "FTP" is only the display label for the
  single power-anchor value (one number, not two).
- **CP/W′ model is optional**, engages only when the user supplies CP + W′.
  Canonical algorithm: **Skiba 2015 W′BAL-INT** (not the 2012 version).
- A 3-tier calculator is *designed* (direct entry / multi-effort linear /
  3-min all-out) but **not yet coded**.

### RPE (spec §6)
- Borg CR10, **always a range** `[low-high]`. Single value only as `[1-1]`/`[10-10]`.
- Confirmed zone→RPE table (§6.2): Recovery 1-2 · Endurance 2-4 · Tempo 3-5 ·
  Threshold 5-7 · VO2max 7-9 · Anaerobic 8-10 · Neuromuscular 9-10.
- Derivation (§6.3): flat segment → midpoint→zone→band; ramp → floor of lower
  endpoint's band to ceiling of upper endpoint's band.

### Mandatory session structure (spec §11) — flexible, engine-reasoned
- Every session = **Warmup + Main Set + Cooldown**, always.
- **Durations are flexible and engine-reasoned**; the 10-min warmup / 5-min
  cooldown figures are **caps, not targets**. Short sessions get short warmups.
- **Power mode:** warmup = ascending **ramp**; cooldown = descending ramp or a
  fixed easy block.
- **HR mode:** warmup = ascending **staircase of steps** (NOT a ramp — HR can't
  follow a smooth ramp); cooldown = fewest steps possible, ideally one block.
- **Prep block** (the only always-present block): `45-55%` (power) /
  `60-80% LTHR` (HR), duration **flexible 1–2 min**, always present.

### Output / export (spec §12)
- Engine writes **directly in intervals.icu syntax** (no narrative layer). Export
  is a thin wrapper that uploads the `.md` as-is.
- **Output-validation gate** rejects out-of-scope constructs (distance `mtr`/`km`,
  `freeride`, `% HR` vs max-HR, `% Pace`) before export.
- Repeat blocks are **never nested**; divided patterns = sequential blocks.

### TSS / IF (spec §16)
- Exact algebra: `TSS = hours × IF² × 100`. **Simplified NP** (4th-power
  weighted, no 30s rolling average) — option A, robust; engine TSS is a
  **design-time estimate**, intervals.icu computes the authoritative value.
- **Always round** to valid syntax; report the **real TSS of the rounded
  workout**, not the target.
- **Infeasibility is reported with numbers, never forced** (e.g. TSS target that
  can't fit in max duration). Budget conflicts likewise.

### Progressions (spec §15) — time-budget driven
- Driver = athlete's **available time per session**, not a week pattern or any
  author's recipe.
- **Case A** (initial duration only): grow to the stimulus's **physiological
  ceiling**, which the engine **researches live**; note graduation to next
  stimulus at the ceiling.
- **Case B** (initial + max): develop ideal load between the two.
- Only fixed floor: the sequence must be **coherent and directional**. *How* it
  progresses is engine-reasoned. No imposed methodology (the Cusick example was
  inspiration, never a rule).
- **Budget conservation is arithmetic** (Python): warmup+prep+cooldown+main ≤
  budget. The *split* of that budget is engine-reasoned.

### Catalog / anti-repetition (spec §17) — memory, not a rule engine
- **SQLite catalog** = the engine's own **memory + reusable library**. NOT a
  mechanical "signature comparison" (that approach was rejected — it broke
  natural progressions like `4×10`→`4×12:30`).
- Variety comes from the engine **reasoning over its own catalog** + knowledge +
  web search. `pattern_signature` concept was **dissolved**, not deferred.
- Dominant/subordinate boundary: the requested stimulus stays dominant; any
  complementary stimuli are subordinate (open-ended, engine-discovered).
- `progression_id` exempts within-progression repetition from penalty.

### Reasoning layer architecture (spec §9)
- **Claude API** via the `anthropic` SDK + **tool-use** (structured proposal) +
  optional **web search**. Not a Claude Project (not callable from code).
- Claude **proposes structure**; Python **validates against hard rules, does all
  math, renders**. Rejected proposals are discarded & re-requested — never
  silently fixed, never accepted blind.
- `--offline` mode runs the deterministic core without API calls.
- Future-web-portable: no Claude Project dependency, no static KB to port.

---

## 3. What's BUILT and TESTED (43 tests passing)

### Deterministic core (Phase 1)
| Module | Role |
|---|---|
| `zones.py` | Friel power/HR zones, independent |
| `rpe.py` | RPE derivation (flat midpoint / ramp endpoints) |
| `render.py` | intervals.icu syntax + rounding + output gate |
| `tss.py` | TSS/IF/NP math, single-unknown resolution, infeasibility |
| `catalog.py` | SQLite memory + library, persistent |
| `models.py` | request/session dataclasses |
| `structure.py` | mandatory structure (power ramp / HR staircase), flexible durations, budget conflict |
| `assembler.py` | final `.md` assembly + real TSS |
| `generator.py` | Phase-1 end-to-end (provisional placeholder structure) |
| `cli.py` | command-line interface, `--offline` |

### Reasoning layer (Phase 2)
| Module | Role |
|---|---|
| `proposal.py` | tool-use contract + hard-rule validator (incl. budget arithmetic) |
| `claude_client.py` | prompt building, API call (injectable transport), web search |
| `build_from_proposal.py` | validated proposal → engine components |
| `generator_v2.py` | Phase-2 single-session orchestration (validate→build→render) |

### Progressions
| Module | Role |
|---|---|
| `progression.py` | progression tool contract + per-session validation |
| `generate_progression.py` | full reasoned progression, shared `progression_id` |

### Test coverage
- TSS/IF math with **hand-calculated reference cases** (spec §16.5 mandate).
- RPE derivation (flat + ramp).
- Rendering + output gate (accepts `% LTHR`, rejects distance/freeride/`% HR`).
- End-to-end power & HR generation.
- HR staircase (not ramp) + single-block cooldown; power unchanged.
- Phase-2 integration via **mock transport**: valid proposal flows through;
  invalid ones (complementary dominates, cross-mode zone, nested repeat) rejected.
- Progression: volume/TSS up while IF stable, shared `progression_id`, valid `.md`.
- **Budget conservation**: fitting session passes, over-budget rejected with exact overage.

---

## 4. Companion artifacts

| File | What |
|---|---|
| `cycling_workout_generator_specification.md` | Canonical spec, v2.3 (~460 lines) |
| `workout_engine_schema.json` | Validated lean JSON Schema (decision 2a) |
| `workout_engine/` | The engine package + tests + README |

---

## 5. What remains (next candidate steps)

1. **Wire the budget logic into progressions** so Day-1 (e.g. 30 min) truly fits
   and grows from there (single-session budget conservation is done; progression
   path should use the same).
2. **CP/W′ calculator** (spec §7.2) — designed, not coded.
3. **intervals.icu export script** — upload the `.md` via API (thin wrapper).
4. **Real-API run** on the user's machine (`pip install anthropic`,
   `ANTHROPIC_API_KEY`) to see Claude reason live vs. the mock.
5. (Later, if ever) the future web front-end — architecture already kept
   portable (no Claude Project, no static KB).

---

## 6. Known notes / honest flags

- All "creative" structure in Phase-1 `generator.py` is **provisional placeholder**
  — superseded by Phase-2 reasoning. Kept for `--offline` and as durable plumbing.
- The spec's illustrative RPE/structure examples are explicitly **examples, not
  rules** throughout — this was a recurring correction and is now baked in.
- Web search + the catalog are **additive**, not exclusive; neither is a KB.
