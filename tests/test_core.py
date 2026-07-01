"""
test_core.py — Tests for the deterministic mechanical core.

Includes hand-calculated reference cases for the TSS/IF math (spec 16.5
mandates this, given the project's history of errors in this exact area).
Run with:  python -m pytest tests/ -v   (or plain `python tests/test_core.py`)
"""

from __future__ import annotations
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import tss, rpe, render, zones


# ============================================================
# TSS / IF / duration algebra — hand-calculated references
# ============================================================

def test_tss_textbook_one_hour_at_ftp():
    # 1 hour at IF 1.0 == exactly 100 TSS (the definition).
    assert abs(tss.tss_from(3600, 1.0) - 100.0) < 1e-9


def test_tss_half_hour_at_if_one():
    # 0.5 h * 1.0^2 * 100 = 50
    assert abs(tss.tss_from(1800, 1.0) - 50.0) < 1e-9


def test_tss_one_hour_at_if_0_8():
    # 1 h * 0.8^2 * 100 = 64
    assert abs(tss.tss_from(3600, 0.8) - 64.0) < 1e-9


def test_duration_from_tss_and_if():
    # Need TSS 64 at IF 0.8 -> 1 hour = 3600 s
    assert abs(tss.duration_from(64, 0.8) - 3600.0) < 1e-6


def test_if_from_tss_and_duration():
    # TSS 64 in 1 hour -> IF 0.8
    assert abs(tss.if_from(64, 3600) - 0.8) < 1e-9


def test_round_trip_consistency():
    # Build TSS from (dur, IF), recover IF from (TSS, dur), recover dur.
    dur, IF = 2700, 0.85
    t = tss.tss_from(dur, IF)
    assert abs(tss.if_from(t, dur) - IF) < 1e-9
    assert abs(tss.duration_from(t, IF) - dur) < 1e-6


# ============================================================
# Normalized Power (simplified) — hand-calculated
# ============================================================

def test_np_constant_power_equals_that_power():
    # A single steady segment: NP == that power.
    segs = [tss.Segment(3600, 0.9)]
    assert abs(tss.normalized_power_frac(segs) - 0.9) < 1e-9


def test_np_two_equal_duration_segments():
    # Two 600s segments at 0.6 and 1.0.
    # NP = ((600*0.6^4 + 600*1.0^4)/1200)^(1/4)
    #    = ((0.1296 + 1.0)/2)^(1/4) = (0.5648)^0.25
    segs = [tss.Segment(600, 0.6), tss.Segment(600, 1.0)]
    expected = (0.5648) ** 0.25
    assert abs(tss.normalized_power_frac(segs) - expected) < 1e-9


def test_np_weights_high_power_more():
    # NP must exceed the simple time-average because of 4th-power weighting.
    segs = [tss.Segment(600, 0.6), tss.Segment(600, 1.0)]
    simple_avg = 0.8
    assert tss.normalized_power_frac(segs) > simple_avg


# ============================================================
# Work-segment intensity resolution — hand-calculated
# ============================================================

def test_solve_work_power_recovers_known_answer():
    # Construct a session whose true NP we know, then solve for the work power
    # and confirm we get it back.
    # Warmup-ish: 600s @ 0.5 ; Work: 1800s @ P ; recovery 600s @ 0.5
    # Choose P = 0.9. total = 3000s.
    # NP^4 = (600*0.5^4 + 1800*0.9^4 + 600*0.5^4)/3000
    known = [tss.Segment(600, 0.5), tss.Segment(600, 0.5)]
    work_p = 0.9
    total = 3000.0
    work_t = 1800.0
    np4 = (600 * 0.5**4 + 1800 * work_p**4 + 600 * 0.5**4) / total
    np_target = np4 ** 0.25
    solved = tss.solve_work_power_frac(
        np_target_frac=np_target,
        total_seconds=total,
        known_segments=known,
        work_total_seconds=work_t,
    )
    assert abs(solved - work_p) < 1e-9


def test_solve_work_power_infeasible_raises():
    # Demand an NP so low that even zero work power can't bring it down:
    # known segments alone already exceed the target.
    known = [tss.Segment(1000, 0.95)]
    try:
        tss.solve_work_power_frac(
            np_target_frac=0.40,  # absurdly low vs 0.95 known
            total_seconds=2000,
            known_segments=known,
            work_total_seconds=1000,
        )
        assert False, "expected InfeasibleError"
    except tss.InfeasibleError:
        pass


# ============================================================
# RPE derivation (spec 6.3)
# ============================================================

def test_rpe_flat_recovery():
    # 45-55% power -> mid 50% -> ActiveRecovery -> [1,2]
    assert rpe.rpe_for_flat("power", 45, 55) == (1, 2)


def test_rpe_flat_tempo():
    # 84-90% -> mid 87% -> Tempo -> [3,5]
    assert rpe.rpe_for_flat("power", 84, 90) == (3, 5)


def test_rpe_ramp_warmup_45_75():
    # 45-75% -> lower 45%=ActiveRecovery(floor 1), upper 75%=... 75 is the
    # boundary; zone_for_percent uses low<=pct<high, so 75 falls in Tempo
    # (75-90). Tempo ceiling = 5. Expect (1,5).
    assert rpe.rpe_for_ramp("power", 45, 75) == (1, 5)


def test_rpe_ramp_descending_same_as_ascending():
    # Direction independent: 75-45 same band as 45-75.
    assert rpe.rpe_for_ramp("power", 75, 45) == rpe.rpe_for_ramp("power", 45, 75)


# ============================================================
# Rendering + output validation gate
# ============================================================

def test_format_duration_variants():
    assert render.format_duration(90) == "1m30s"
    assert render.format_duration(600) == "10m"
    assert render.format_duration(30) == "30s"
    assert render.format_duration(3600) == "1h"


def test_render_flat_power_line():
    line = render.render_step_line(
        mode="power", duration_seconds=600,
        flat_low=84, flat_high=90, rpe_low=3, rpe_high=5,
    )
    assert line == "- 10m 84-90% [RPE 3-5]"


def test_render_ramp_hr_line_uses_lthr():
    line = render.render_step_line(
        mode="hr", duration_seconds=600, is_ramp=True,
        ramp_start=45, ramp_end=75, rpe_low=1, rpe_high=4,
    )
    assert line == "- 10m ramp 45-75% LTHR [RPE 1-4]"


def test_render_with_cadence():
    line = render.render_step_line(
        mode="power", duration_seconds=600,
        flat_low=84, flat_high=90, cadence_low=85, cadence_high=85,
        rpe_low=3, rpe_high=5,
    )
    assert line == "- 10m 84-90% 85rpm [RPE 3-5]"


def test_output_gate_rejects_distance():
    try:
        render.validate_output("- 5km 80%")
        assert False, "expected rejection"
    except render.OutputValidationError:
        pass


def test_output_gate_rejects_freeride():
    try:
        render.validate_output("- 20m freeride")
        assert False
    except render.OutputValidationError:
        pass


def test_output_gate_rejects_pct_hr():
    try:
        render.validate_output("- 10m 80% HR")
        assert False
    except render.OutputValidationError:
        pass


def test_output_gate_allows_valid_lthr():
    # % LTHR must NOT be rejected even though it contains 'HR' substring.
    render.validate_output("- 10m 80-85% LTHR [RPE 3-4]")  # should not raise


def test_output_gate_allows_valid_power():
    render.validate_output("- 10m 84-90% [RPE 3-5]")


# ============================================================
# Zones
# ============================================================

def test_power_and_hr_tempo_are_independent():
    p = zones.zone_by_name("power", "Tempo")
    h = zones.zone_by_name("hr", "Tempo")
    # Same name, different systems / bounds — never mapped to each other.
    assert p.low_pct == 75 and p.high_pct == 90
    assert h.low_pct == 90 and h.high_pct == 94


def test_zone_for_percent_power():
    assert zones.zone_for_percent("power", 50).name == "ActiveRecovery"
    assert zones.zone_for_percent("power", 87).name == "Tempo"
    assert zones.zone_for_percent("power", 200).name == "Neuromuscular"


if __name__ == "__main__":
    # Minimal runner if pytest isn't used.
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
        except Exception:
            failed += 1
            print(f"FAIL: {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed, {len(fns)} total")
    sys.exit(1 if failed else 0)


# ============================================================
# End-to-end generation flow (Phase-1 provisional structure)
# ============================================================

def test_generate_single_power_endtoend():
    from engine.models import GenerationRequest
    from engine.generator import generate_single
    sess = generate_single(
        GenerationRequest(kind="single_session", mode="power", requested_zone="Tempo"),
        seed=42,
    )
    md = sess.markdown_output
    # mandatory structure present
    assert "# Warmup" in md and "# Main Set" in md and "# Cooldown" in md
    # the one fixed block always present
    assert "2m 45-55%" in md
    # power mode: no LTHR, no forbidden constructs
    assert "LTHR" not in md
    assert "mtr" not in md and "freeride" not in md
    assert sess.estimated_tss > 0


def test_generate_single_hr_uses_lthr():
    from engine.models import GenerationRequest
    from engine.generator import generate_single
    sess = generate_single(
        GenerationRequest(kind="single_session", mode="hr", requested_zone="Tempo"),
        seed=1,
    )
    assert "LTHR" in sess.markdown_output
    assert "% HR" not in sess.markdown_output  # never max-HR relative


def test_generate_constraint_conflict_reported():
    from engine.models import GenerationRequest
    from engine.generator import generate_single
    from engine.structure import ConstraintConflict
    # TSS 100 at IF 0.6 needs ~46 min; cap at 20 min -> conflict reported.
    req = GenerationRequest(
        kind="single_session", mode="power", requested_zone="Tempo",
        target_tss=100, target_if=0.6, max_available_seconds=1200,
    )
    try:
        generate_single(req, seed=1)
        assert False, "expected ConstraintConflict"
    except ConstraintConflict as e:
        assert "TSS" in e.report and "max available" in e.report


def test_catalog_records_generation():
    import tempfile, os
    from engine.models import GenerationRequest
    from engine.generator import generate_single
    from engine.catalog import Catalog
    db = os.path.join(tempfile.mkdtemp(), "c.sqlite")
    cat = Catalog(db)
    generate_single(
        GenerationRequest(kind="single_session", mode="power", requested_zone="Tempo"),
        seed=7, catalog=cat,
    )
    assert cat.count() == 1
    recent = cat.recent(mode="power", dominant_zone="Tempo")
    assert len(recent) == 1 and recent[0].markdown
    cat.close()


# ============================================================
# HR-mode staircase warmup + single-block cooldown (spec 11.1/11.3)
# ============================================================

def test_hr_warmup_is_staircase_not_ramp():
    from engine.models import GenerationRequest
    from engine.generator import generate_single
    sess = generate_single(
        GenerationRequest(kind="single_session", mode="hr", requested_zone="Tempo"),
        seed=1,
    )
    md = sess.markdown_output
    # HR warmup must NOT use 'ramp'
    warmup_section = md.split("# Main Set")[0]
    assert "ramp" not in warmup_section
    # must contain the fixed HR prep block
    assert "2m 60-80% LTHR" in md


def test_hr_cooldown_single_block_no_ramp():
    from engine.models import GenerationRequest
    from engine.generator import generate_single
    sess = generate_single(
        GenerationRequest(kind="single_session", mode="hr", requested_zone="Tempo"),
        seed=2,
    )
    cooldown_section = sess.markdown_output.split("# Cooldown")[1]
    assert "ramp" not in cooldown_section
    # exactly one step line (one '- ' line) in the cooldown
    step_lines = [l for l in cooldown_section.splitlines() if l.strip().startswith("- ")]
    assert len(step_lines) == 1


def test_power_warmup_still_uses_ramp():
    from engine.models import GenerationRequest
    from engine.generator import generate_single
    sess = generate_single(
        GenerationRequest(kind="single_session", mode="power", requested_zone="Tempo"),
        seed=1,
    )
    assert "ramp 45-75%" in sess.markdown_output
    assert "2m 45-55%" in sess.markdown_output  # power prep block unchanged


def test_hr_staircase_respects_10min_limit():
    from engine.structure import build_warmup_hr_staircase
    # 6 steps x 2min = 12min > 10min limit -> must raise
    steps = [(50, 60, 120)] * 6
    try:
        build_warmup_hr_staircase(steps)
        assert False, "expected limit violation"
    except ValueError:
        pass


def test_catalog_records_hr_generation():
    """Regression (C1): HR mode + catalog crashed with AttributeError because
    warmup.ramp is None in HR mode (staircase lives in warmup.steps)."""
    import tempfile, os
    from engine.models import GenerationRequest
    from engine.generator import generate_single
    from engine.catalog import Catalog
    db = os.path.join(tempfile.mkdtemp(), "hr.sqlite")
    cat = Catalog(db)
    sess = generate_single(
        GenerationRequest(kind="single_session", mode="hr", requested_zone="Tempo"),
        seed=3, catalog=cat,
    )
    assert cat.count() == 1
    entry = cat.recent(mode="hr", dominant_zone="Tempo")[0]
    # duration must equal the real built total (staircase + prep + main + cooldown)
    warm = sess.warmup.prep.duration_seconds + sum(
        s.duration_seconds for s in sess.warmup.steps)
    main = sum(b.repeats * sum(s.duration_seconds for s in b.steps)
               for b in sess.main_set)
    cool = sum(s.duration_seconds for s in sess.cooldown)
    assert entry.duration_seconds == warm + main + cool
    cat.close()


# ============================================================
# hrTSS-type estimate for HR mode (spec 16.6)
# ============================================================

def test_hr_equivalent_if_anchors():
    # Anchors: LTHR -> 1.0; 70% LTHR -> 0.55; floor at 0.
    assert abs(tss.hr_equivalent_if(1.00) - 1.00) < 1e-9
    assert abs(tss.hr_equivalent_if(0.70) - 0.55) < 1e-9
    assert tss.hr_equivalent_if(0.20) == 0.0


def test_hr_session_tss_hand_calculated():
    # 30 min at 92% LTHR: IF_eq = 1.5*0.92-0.5 = 0.88
    # TSS = 0.5h * 0.88^2 * 100 = 38.72
    segs = [tss.Segment(1800, 0.92)]
    t, eq_if = tss.hr_session_tss(segs)
    assert abs(t - 38.72) < 1e-9
    assert abs(eq_if - 0.88) < 1e-9


def test_hr_session_tss_segmentwise_accumulation():
    # Two segments accumulate independently (no NP-style weighting):
    # 10 min @ 70% (IF 0.55) -> (1/6)*0.3025*100 = 5.041666...
    # 20 min @ 92% (IF 0.88) -> (1/3)*0.7744*100 = 25.81333...
    segs = [tss.Segment(600, 0.70), tss.Segment(1200, 0.92)]
    t, _ = tss.hr_session_tss(segs)
    assert abs(t - (5.0416666667 + 25.8133333333)) < 1e-6


def test_hr_generation_reports_hrtss():
    """End-to-end HR session must report the hrTSS-type estimate, not
    power-NP math applied to %LTHR."""
    from engine.models import GenerationRequest
    from engine.generator import generate_single
    from engine import assembler
    sess = generate_single(
        GenerationRequest(kind="single_session", mode="hr", requested_zone="Tempo"),
        seed=5,
    )
    # Recompute independently with the hr path and compare.
    t, eq = assembler.compute_tss_if(sess.warmup, sess.main_set, sess.cooldown,
                                     mode="hr")
    assert abs(sess.estimated_tss - round(t, 1)) < 1e-9
    assert sess.estimated_tss > 0
