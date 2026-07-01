"""
test_phase2.py — Phase-2 integration tests using a MOCK Claude transport.

These verify the full reasoning->validation->build->render pipeline without
any API key or network. The mock returns canned proposals; the test asserts
the engine validates, rebuilds, renders, and catalogs them correctly — and
rejects bad proposals.
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.models import GenerationRequest
from engine.generator_v2 import generate_single_v2
from engine.proposal import validate_proposal, ProposalRejected


# --- Mock transports --------------------------------------------------------

def mock_power_tempo(*_args, **_kw):
    """A valid power-mode Tempo proposal: 4x10min Tempo with short VO2 peaks
    (subordinate), classic interval."""
    return {
        "structural_pattern": "classic_interval",
        "summary": "Tempo 4x10min with short subordinate VO2 surges",
        "complementary_stimuli": [{"zone": "VO2Max",
                                   "rationale": "short surges enrich the tempo block"}],
        "main_set": [
            {"element": "repeat", "repeats": 4, "steps": [
                {"duration_seconds": 540, "low_pct": 80, "high_pct": 88,
                 "zone_name": "Tempo"},
                {"duration_seconds": 30, "low_pct": 108, "high_pct": 115,
                 "zone_name": "VO2Max"},
                {"duration_seconds": 180, "low_pct": 55, "high_pct": 60,
                 "zone_name": "Endurance", "is_recovery": True},
            ]},
        ],
    }


def mock_hr_tempo(*_args, **_kw):
    """A valid HR-mode proposal with a staircase warmup."""
    return {
        "structural_pattern": "classic_interval",
        "summary": "HR Tempo 3x8min",
        "hr_warmup_staircase": [[50, 60, 120], [60, 70, 120], [70, 80, 120]],
        "main_set": [
            {"element": "repeat", "repeats": 3, "steps": [
                {"duration_seconds": 480, "low_pct": 90, "high_pct": 93,
                 "zone_name": "Tempo"},
                {"duration_seconds": 180, "low_pct": 70, "high_pct": 80,
                 "zone_name": "Aerobic", "is_recovery": True},
            ]},
        ],
    }


def mock_complementary_dominates(*_args, **_kw):
    """INVALID: complementary VO2 work exceeds dominant Tempo work."""
    return {
        "structural_pattern": "classic_interval",
        "summary": "bad: VO2 dominates",
        "main_set": [
            {"element": "step", "duration_seconds": 120, "low_pct": 80,
             "high_pct": 88, "zone_name": "Tempo"},
            {"element": "step", "duration_seconds": 600, "low_pct": 108,
             "high_pct": 115, "zone_name": "VO2Max"},
        ],
    }


def mock_cross_mode_zone(*_args, **_kw):
    """INVALID for power mode: uses an HR-only zone name."""
    return {
        "structural_pattern": "continuous",
        "summary": "bad: HR zone in power mode",
        "main_set": [
            {"element": "step", "duration_seconds": 600, "low_pct": 94,
             "high_pct": 99, "zone_name": "SubThreshold"},  # HR-only zone
        ],
    }


def mock_nested_repeat(*_args, **_kw):
    """INVALID: a repeat nested inside a repeat step."""
    return {
        "structural_pattern": "divided_split",
        "summary": "bad: nested",
        "main_set": [
            {"element": "repeat", "repeats": 2, "steps": [
                {"element": "repeat", "repeats": 3, "low_pct": 80, "high_pct": 88,
                 "zone_name": "Tempo", "duration_seconds": 300},
            ]},
        ],
    }


# --- Integration tests ------------------------------------------------------

def test_power_proposal_flows_to_markdown():
    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Tempo")
    sess = generate_single_v2(req, transport=mock_power_tempo)
    md = sess.markdown_output
    assert "# Warmup" in md and "# Main Set" in md and "# Cooldown" in md
    assert "2m 45-55%" in md                 # fixed power prep block
    assert "4x" in md                        # 4 repeats
    assert sess.structural_pattern == "classic_interval"
    assert sess.complementary_zones == ["VO2Max"]
    assert sess.estimated_tss > 0
    assert "mtr" not in md and "freeride" not in md


def test_hr_proposal_uses_staircase_and_lthr():
    req = GenerationRequest(kind="single_session", mode="hr",
                            requested_zone="Tempo")
    sess = generate_single_v2(req, transport=mock_hr_tempo)
    md = sess.markdown_output
    assert "LTHR" in md and "% HR" not in md
    warmup_section = md.split("# Main Set")[0]
    assert "ramp" not in warmup_section      # staircase, not ramp
    assert "2m 60-80% LTHR" in md            # fixed HR prep block


def test_complementary_cannot_dominate():
    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Tempo")
    try:
        generate_single_v2(req, transport=mock_complementary_dominates)
        assert False, "expected rejection"
    except ProposalRejected:
        pass


def test_cross_mode_zone_rejected():
    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Tempo")
    try:
        generate_single_v2(req, transport=mock_cross_mode_zone)
        assert False, "expected rejection"
    except ProposalRejected:
        pass


def test_nested_repeat_rejected():
    # validate directly (the nested form may not even match the build path)
    try:
        validate_proposal(mock_nested_repeat(), mode="power",
                          dominant_zone="Tempo")
        assert False, "expected rejection"
    except ProposalRejected:
        pass


def test_catalog_records_v2():
    import tempfile
    from engine.catalog import Catalog
    db = os.path.join(tempfile.mkdtemp(), "v2.sqlite")
    cat = Catalog(db)
    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Tempo")
    generate_single_v2(req, transport=mock_power_tempo, catalog=cat)
    assert cat.count() == 1
    e = cat.recent(mode="power", dominant_zone="Tempo")[0]
    assert "VO2" in e.summary or e.complementary == ["VO2Max"]
    cat.close()


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in fns:
        try:
            fn(); passed += 1
        except Exception:
            failed += 1; print(f"FAIL: {fn.__name__}"); traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed, {len(fns)} total")
    sys.exit(1 if failed else 0)


# ============================================================
# Reasoned progressions (spec 15, no-KB free reasoning spec 9.6)
# ============================================================

def _mock_tempo_progression(system, user, tools, web):
    def cont(minutes):
        return {"structural_pattern": "continuous",
                "summary": f"Tempo {minutes}min continuous",
                "main_set": [{"element": "step", "duration_seconds": minutes*60,
                              "low_pct": 80, "high_pct": 88, "zone_name": "Tempo"}]}
    def interval(reps, minutes):
        return {"structural_pattern": "classic_interval",
                "summary": f"Tempo {reps}x{minutes}min",
                "main_set": [{"element": "repeat", "repeats": reps, "steps": [
                    {"duration_seconds": minutes*60, "low_pct": 80, "high_pct": 88,
                     "zone_name": "Tempo"},
                    {"duration_seconds": 180, "low_pct": 55, "high_pct": 60,
                     "zone_name": "Endurance", "is_recovery": True}]}]}
    return {
        "reasoning": "Progress volume 30->90 min, alternate continuous/interval.",
        "graduation_note": "Graduate to Sweet Spot after 90 min Tempo.",
        "sessions": [cont(30), interval(2, 20), cont(45), interval(2, 30),
                     cont(60), interval(2, 45), cont(90)],
    }


def test_progression_volume_progresses_intensity_stable():
    from engine.models import GenerationRequest
    from engine.generate_progression import generate_progression
    req = GenerationRequest(kind="progression", mode="power", requested_zone="Tempo")
    result = generate_progression(req, transport=_mock_tempo_progression)
    assert len(result.sessions) == 7
    tsss = [s.estimated_tss for s in result.sessions]
    ifs = [s.estimated_if for s in result.sessions]
    # Volume/TSS trends up overall; IF stays within a tight band (power not driven up).
    assert tsss[-1] > tsss[0]
    assert max(ifs) - min(ifs) < 0.1
    assert result.graduation_note is not None


def test_progression_shares_one_progression_id():
    from engine.models import GenerationRequest
    from engine.generate_progression import generate_progression
    req = GenerationRequest(kind="progression", mode="power", requested_zone="Tempo")
    result = generate_progression(req, transport=_mock_tempo_progression)
    ids = {s.progression_id for s in result.sessions}
    assert len(ids) == 1 and result.progression_id in ids


def test_progression_each_session_valid_md():
    from engine.models import GenerationRequest
    from engine.generate_progression import generate_progression
    from engine.render import validate_output
    req = GenerationRequest(kind="progression", mode="power", requested_zone="Tempo")
    result = generate_progression(req, transport=_mock_tempo_progression)
    for s in result.sessions:
        assert "# Warmup" in s.markdown_output
        assert "# Main Set" in s.markdown_output
        assert "# Cooldown" in s.markdown_output
        validate_output(s.markdown_output)  # passes the output gate


# ============================================================
# Regression test: progression Day-1 budget conservation
# (was broken - progressions never enforced budget; fixed)
# ============================================================

def test_progression_day1_oversized_warmup_rejected():
    from engine.models import GenerationRequest
    from engine.generate_progression import generate_progression
    from engine.proposal import ProposalRejected

    def mock_oversized(system, user, tools, web):
        return {
            "reasoning": "t", "graduation_note": None,
            "sessions": [{
                "structural_pattern": "classic_interval", "summary": "bad",
                "warmup_seconds": 600, "prep_seconds": 120, "cooldown_seconds": 300,
                "main_set": [{"element": "repeat", "repeats": 3, "steps": [
                    {"duration_seconds": 600, "low_pct": 80, "high_pct": 88,
                     "zone_name": "Tempo"}]}],
            }],
        }
    req = GenerationRequest(kind="progression", mode="power",
                            requested_zone="Tempo", target_duration_seconds=1800)
    try:
        generate_progression(req, transport=mock_oversized)
        assert False, "expected rejection: 47min session in a 30min Day-1 budget"
    except ProposalRejected:
        pass


def test_progression_day1_fits_budget_exactly():
    from engine.models import GenerationRequest
    from engine.generate_progression import generate_progression

    def mock_fits(system, user, tools, web):
        return {
            "reasoning": "t", "graduation_note": None,
            "sessions": [{
                "structural_pattern": "classic_interval",
                "summary": "Tempo 2x10min in 30min budget",
                "warmup_seconds": 300, "prep_seconds": 60, "cooldown_seconds": 120,
                "main_set": [{"element": "repeat", "repeats": 2, "steps": [
                    {"duration_seconds": 600, "low_pct": 80, "high_pct": 88,
                     "zone_name": "Tempo"},
                    {"duration_seconds": 60, "low_pct": 55, "high_pct": 60,
                     "zone_name": "Endurance", "is_recovery": True}]}],
            }],
        }
    req = GenerationRequest(kind="progression", mode="power",
                            requested_zone="Tempo", target_duration_seconds=1800)
    result = generate_progression(req, transport=mock_fits)
    md = result.sessions[0].markdown_output
    assert "5m ramp" in md  # engine-sized warmup, not the 10min default
    assert "1m 45-55%" in md  # engine-sized prep, not the 2min default


# ============================================================
# Regression test: TSS target verification (was never checked; fixed)
# ============================================================

def test_tss_target_far_off_is_rejected():
    from engine.models import GenerationRequest
    from engine.generator_v2 import generate_single_v2
    from engine.proposal import ProposalRejected

    def mock_way_off(system, user, tools, web):
        return {
            "structural_pattern": "continuous", "summary": "too easy",
            "warmup_seconds": 300, "prep_seconds": 60, "cooldown_seconds": 120,
            "main_set": [{"element": "step", "duration_seconds": 1200,
                          "low_pct": 56, "high_pct": 60, "zone_name": "Endurance"}],
        }
    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Endurance", target_tss=80)
    try:
        generate_single_v2(req, transport=mock_way_off)
        assert False, "expected rejection: real TSS far below target 80"
    except ProposalRejected:
        pass


def test_tss_target_close_is_accepted():
    from engine.models import GenerationRequest
    from engine.generator_v2 import generate_single_v2

    def mock_close(system, user, tools, web):
        return {
            "structural_pattern": "continuous", "summary": "tuned close",
            "warmup_seconds": 300, "prep_seconds": 60, "cooldown_seconds": 120,
            "main_set": [{"element": "step", "duration_seconds": 2520,
                          "low_pct": 68, "high_pct": 72, "zone_name": "Endurance"}],
        }
    # 41 TSS is physiologically reachable at ~70% FTP for this duration.
    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Endurance", target_tss=41)
    sess = generate_single_v2(req, transport=mock_close)
    assert abs(sess.estimated_tss - 41) / 41 < 0.15  # within tolerance


def test_undeclared_complementary_zone_rejected():
    from engine.proposal import validate_proposal, ProposalRejected
    bad = {
        "structural_pattern": "classic_interval", "summary": "undeclared",
        "main_set": [{"element": "repeat", "repeats": 3, "steps": [
            {"duration_seconds": 540, "low_pct": 80, "high_pct": 88, "zone_name": "Tempo"},
            {"duration_seconds": 30, "low_pct": 108, "high_pct": 115, "zone_name": "VO2Max"},
        ]}],
    }
    try:
        validate_proposal(bad, mode="power", dominant_zone="Tempo")
        assert False, "expected rejection: VO2Max used but not declared"
    except ProposalRejected:
        pass


# ============================================================
# Budget floor: deliberately loose (flexibility prioritized per
# user decision) - minor shortfalls pass, considerable ones don't
# ============================================================

def test_minor_budget_shortfall_is_allowed():
    from engine.proposal import validate_proposal
    # 58 min of a 60-min budget (real-world case, ~3.3% under) must pass.
    proposal = {
        "structural_pattern": "continuous", "summary": "minor shortfall ok",
        "warmup_seconds": 600, "prep_seconds": 60, "cooldown_seconds": 300,
        "main_set": [
            {"element": "step", "duration_seconds": 600, "low_pct": 56,
             "high_pct": 63, "zone_name": "Endurance"},
            {"element": "step", "duration_seconds": 600, "low_pct": 63,
             "high_pct": 68, "zone_name": "Endurance"},
            {"element": "step", "duration_seconds": 600, "low_pct": 68,
             "high_pct": 75, "zone_name": "Endurance"},
            {"element": "repeat", "repeats": 3, "steps": [
                {"duration_seconds": 180, "low_pct": 68, "high_pct": 75,
                 "zone_name": "Endurance"},
                {"duration_seconds": 60, "low_pct": 56, "high_pct": 60,
                 "zone_name": "Endurance", "is_recovery": True}]},
        ],
    }
    validate_proposal(proposal, mode="power", dominant_zone="Endurance",
                      total_budget_seconds=3600)  # must not raise


def test_considerable_budget_shortfall_is_rejected():
    from engine.proposal import validate_proposal, ProposalRejected
    # 35 min of a 60-min budget (~58%, well below the 80% floor) must reject.
    proposal = {
        "structural_pattern": "continuous", "summary": "way too short",
        "warmup_seconds": 300, "prep_seconds": 60, "cooldown_seconds": 120,
        "main_set": [{"element": "step", "duration_seconds": 1620,
                      "low_pct": 65, "high_pct": 70, "zone_name": "Endurance"}],
    }
    try:
        validate_proposal(proposal, mode="power", dominant_zone="Endurance",
                          total_budget_seconds=3600)
        assert False, "expected rejection: 35min session in a 60min budget"
    except ProposalRejected:
        pass


# ============================================================
# Regression tests: C2 (ceiling bypass via omitted durations),
# A3 (floor wrongly applied to max_available), M2 budget side
# ============================================================

def test_omitted_structure_durations_cannot_bypass_ceiling():
    """C2: proposal omits warmup/prep/cooldown; effective defaults must count
    toward the budget ceiling (previously a 30-min request built 45 min)."""
    from engine.models import GenerationRequest
    from engine.generator_v2 import generate_single_v2
    from engine.proposal import ProposalRejected

    def mock_omits(system, user, tools, web):
        return {
            "structural_pattern": "continuous", "summary": "omits durations",
            "main_set": [{"element": "step", "duration_seconds": 1680,
                          "low_pct": 80, "high_pct": 88, "zone_name": "Tempo"}],
        }
    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Tempo", target_duration_seconds=1800)
    try:
        generate_single_v2(req, transport=mock_omits)
        assert False, "expected rejection: defaults blow the 30-min ceiling"
    except ProposalRejected:
        pass


def test_max_available_is_ceiling_only_no_floor():
    """A3: with ONLY max_available given, a session well under the maximum is
    valid — the 80% floor must never apply to a ceiling."""
    from engine.models import GenerationRequest
    from engine.generator_v2 import generate_single_v2

    def mock_40min(system, user, tools, web):
        return {
            "structural_pattern": "classic_interval",
            "summary": "40min tempo under a 60min cap",
            "warmup_seconds": 480, "prep_seconds": 120, "cooldown_seconds": 180,
            "main_set": [{"element": "repeat", "repeats": 3, "steps": [
                {"duration_seconds": 480, "low_pct": 80, "high_pct": 88,
                 "zone_name": "Tempo"},
                {"duration_seconds": 120, "low_pct": 55, "high_pct": 60,
                 "zone_name": "Endurance", "is_recovery": True}]}],
        }
    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Tempo", max_available_seconds=3600)
    sess = generate_single_v2(req, transport=mock_40min)  # must not raise
    assert sess.estimated_tss > 0


def test_target_duration_floor_still_enforced():
    """A3 counterpart: with a TARGET duration, the loose floor still applies."""
    from engine.models import GenerationRequest
    from engine.generator_v2 import generate_single_v2
    from engine.proposal import ProposalRejected

    def mock_too_short(system, user, tools, web):
        return {
            "structural_pattern": "continuous", "summary": "way too short",
            "warmup_seconds": 300, "prep_seconds": 60, "cooldown_seconds": 120,
            "main_set": [{"element": "step", "duration_seconds": 1620,
                          "low_pct": 80, "high_pct": 88, "zone_name": "Tempo"}],
        }
    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Tempo", target_duration_seconds=3600)
    try:
        generate_single_v2(req, transport=mock_too_short)
        assert False, "expected rejection: 35min of a 60-min TARGET"
    except ProposalRejected:
        pass


def test_hr_staircase_sum_governs_budget():
    """M2 (budget side): a declared warmup_seconds that disagrees with the
    staircase must not be what the budget check uses — the staircase sum is
    what gets built, so it is what gets validated."""
    from engine.models import GenerationRequest
    from engine.generator_v2 import generate_single_v2
    from engine.proposal import ProposalRejected

    def mock_hr_mismatch(system, user, tools, web):
        return {
            "structural_pattern": "continuous",
            "summary": "claims 120s warmup, staircase is 480s",
            "warmup_seconds": 120, "prep_seconds": 60, "cooldown_seconds": 120,
            "hr_warmup_staircase": [[50, 60, 120], [60, 70, 120],
                                    [70, 80, 120], [80, 88, 120]],  # 480s real
            "main_set": [{"element": "step", "duration_seconds": 900,
                          "low_pct": 90, "high_pct": 93, "zone_name": "Tempo"}],
        }
    # Budget 25 min: declared math (120+60+120+900=1200s) would pass; the
    # REAL build (480+60+120+900=1560s) exceeds nothing here, so use a budget
    # where the two disagree on the verdict: 1500s (25 min) -> real 1560 > 1500.
    req = GenerationRequest(kind="single_session", mode="hr",
                            requested_zone="Tempo", target_duration_seconds=1500)
    try:
        generate_single_v2(req, transport=mock_hr_mismatch)
        assert False, "expected rejection: real staircase blows the budget"
    except ProposalRejected:
        pass


def test_progression_later_sessions_no_floor_vs_max():
    """A3 in progressions: sessions after Day 1 are capped by max_available
    (ceiling) but never forced to fill it."""
    from engine.models import GenerationRequest
    from engine.generate_progression import generate_progression

    def mock_prog(system, user, tools, web):
        def sess(main_secs):
            return {"structural_pattern": "continuous",
                    "summary": f"tempo {main_secs}s",
                    "warmup_seconds": 300, "prep_seconds": 60,
                    "cooldown_seconds": 120,
                    "main_set": [{"element": "step",
                                  "duration_seconds": main_secs,
                                  "low_pct": 80, "high_pct": 88,
                                  "zone_name": "Tempo"}]}
        # Day 1 fits its 30-min target; Day 2 uses only 40 of the 90-min max.
        return {"reasoning": "t", "graduation_note": None,
                "sessions": [sess(1300), sess(1920)]}
    req = GenerationRequest(kind="progression", mode="power",
                            requested_zone="Tempo",
                            target_duration_seconds=1800,
                            max_available_seconds=5400)
    result = generate_progression(req, transport=mock_prog)  # must not raise
    assert len(result.sessions) == 2


# ============================================================
# C3: deterministic work-intensity resolution (spec 16.2-16.4)
# Hand-calculated reference cases per spec 16.5 mandate.
# ============================================================

def _c3_structure_proposal():
    """3x(10min Tempo work + 3min recovery @55-60), structure only."""
    return {
        "structural_pattern": "classic_interval",
        "summary": "Tempo 3x10min, engine resolves intensity",
        "warmup_seconds": 300, "prep_seconds": 120, "cooldown_seconds": 300,
        "main_set": [{"element": "repeat", "repeats": 3, "steps": [
            {"duration_seconds": 600, "low_pct": 80, "high_pct": 88,
             "zone_name": "Tempo"},
            {"duration_seconds": 180, "low_pct": 55, "high_pct": 60,
             "zone_name": "Endurance", "is_recovery": True}]}],
    }


def test_c3_hand_calculated_solve():
    """Hand-calc (spec 16.5): warmup 300s@0.60 + prep 120s@0.50 + cooldown
    300s@0.60 + 3x(600s work + 180s rec@0.575), T=3060s, target TSS 55
    -> IF=0.804400 -> solved work fraction 0.891479 (89.15%)."""
    from engine import tss as tssmod
    from engine.resolve_intensity import (_classify, solve_dominant_intensity)
    prop = _c3_structure_proposal()
    work, known_main = _classify(prop, "Tempo")
    known = [tssmod.Segment(300, 0.60), tssmod.Segment(120, 0.50),
             tssmod.Segment(300, 0.60)] + known_main
    x = solve_dominant_intensity(work=work, known=known,
                                 np_target_frac=0.804400)
    assert abs(x - 0.891479) < 1e-4


def test_c3_endtoend_tss_target_resolved_not_guessed():
    """End-to-end: TSS 55 target; Claude's proposed 80-88% is structure only,
    the engine resolves ~89% deterministically; real rounded TSS ~= 55."""
    from engine.models import GenerationRequest
    from engine.generator_v2 import generate_single_v2

    def mock_structure(system, user, tools, web):
        return _c3_structure_proposal()

    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Tempo", target_tss=55)
    sess = generate_single_v2(req, transport=mock_structure)
    # Resolved intensity (89 center, width shrunk to fit Tempo 75-90) rendered:
    assert "88-90%" in sess.markdown_output
    # Real TSS of the rounded session lands on the target (rounding-level dev).
    assert abs(sess.estimated_tss - 55) / 55 < 0.03


def test_c3_infeasible_target_reported_with_numbers():
    """Spec 16.3: TSS 90 with this structure needs ~116% -> outside Tempo.
    Hard infeasibility with concrete numbers, never clamped."""
    from engine.models import GenerationRequest
    from engine.generator_v2 import generate_single_v2
    from engine.proposal import ProposalRejected

    def mock_structure(system, user, tools, web):
        return _c3_structure_proposal()

    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Tempo", target_tss=90)
    try:
        generate_single_v2(req, transport=mock_structure)
        assert False, "expected infeasibility"
    except ProposalRejected as e:
        msg = str(e)
        assert "outside" in msg and "closest achievable" in msg


def test_c3_ratio_preserved_multiple_work_steps():
    """Two dominant work steps (mids 80% and 88%): ratios preserved, single
    unknown. Verify the solve reproduces a constructed known answer."""
    from engine import tss as tssmod
    from engine.resolve_intensity import _WorkStep, solve_dominant_intensity
    # Construct: known 600s@0.5; work A 600s@r=1.0, work B 600s@r=1.1 with
    # true x=0.85 -> B=0.935. Compute the NP of that exact session, then solve.
    known = [tssmod.Segment(600, 0.5)]
    x_true = 0.85
    segs = known + [tssmod.Segment(600, x_true), tssmod.Segment(600, 1.1*x_true)]
    np_t = tssmod.normalized_power_frac(segs)
    work = [_WorkStep(600, 0.80, 4.0), _WorkStep(600, 0.88, 4.0)]  # ratio 1.1
    x = solve_dominant_intensity(work=work, known=known, np_target_frac=np_t)
    assert abs(x - x_true) < 1e-9


def test_c3_if_target_verified_after_build():
    """A2 (power): a built session must match a requested IF within tolerance;
    with the resolver in the path this holds by construction."""
    from engine.models import GenerationRequest
    from engine.generator_v2 import generate_single_v2

    def mock_structure(system, user, tools, web):
        return _c3_structure_proposal()

    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Tempo", target_if=0.80)
    sess = generate_single_v2(req, transport=mock_structure)
    assert abs(sess.estimated_if - 0.80) / 0.80 < 0.05


def test_c3_overdetermined_inconsistent_reported():
    """Spec 16.1: TSS + IF + duration all given but mutually inconsistent
    -> clean conflict report, no generation attempt."""
    from engine.models import GenerationRequest
    from engine.generator_v2 import generate_single_v2
    from engine.structure import ConstraintConflict

    def mock_never_called(system, user, tools, web):
        raise AssertionError("transport must not be called on a conflict")

    # TSS 55 at IF 0.8044 implies ~51 min; requesting 30 min contradicts it.
    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Tempo", target_tss=55,
                            target_if=0.8044, target_duration_seconds=1800)
    try:
        generate_single_v2(req, transport=mock_never_called)
        assert False, "expected ConstraintConflict"
    except ConstraintConflict as e:
        assert "inconsistent" in e.report


# ============================================================
# A1 / M3 / m3: zone containment, clean rejections, recovery ceiling
# ============================================================

def test_a1_zone_spill_rejected():
    """A1: a 'Tempo' interval spanning into Threshold/VO2 must be rejected —
    containment, not mere overlap."""
    from engine.proposal import validate_proposal, ProposalRejected
    for lo, hi in ((75, 105), (60, 76), (74, 90)):
        bad = {"structural_pattern": "continuous", "summary": "spill",
               "main_set": [{"element": "step", "duration_seconds": 1200,
                             "low_pct": lo, "high_pct": hi,
                             "zone_name": "Tempo"}]}
        try:
            validate_proposal(bad, mode="power", dominant_zone="Tempo")
            assert False, f"expected rejection for {lo}-{hi}% Tempo"
        except ProposalRejected:
            pass


def test_a1_full_zone_range_accepted():
    """A1 counterpart: boundary-inclusive — 75-90% IS a valid Tempo range
    (exactly as Friel writes the zone), and open-ended Neuromuscular only
    checks its lower bound."""
    from engine.proposal import validate_proposal
    ok_tempo = {"structural_pattern": "continuous", "summary": "full zone",
                "main_set": [{"element": "step", "duration_seconds": 1200,
                              "low_pct": 75, "high_pct": 90,
                              "zone_name": "Tempo"}]}
    validate_proposal(ok_tempo, mode="power", dominant_zone="Tempo")
    ok_neuro = {"structural_pattern": "classic_interval", "summary": "sprints",
                "main_set": [{"element": "repeat", "repeats": 6, "steps": [
                    {"duration_seconds": 10, "low_pct": 150, "high_pct": 200,
                     "zone_name": "Neuromuscular"},
                    {"duration_seconds": 180, "low_pct": 45, "high_pct": 55,
                     "zone_name": "ActiveRecovery", "is_recovery": True}]}]}
    validate_proposal(ok_neuro, mode="power", dominant_zone="Neuromuscular")


def test_m3_missing_fields_clean_rejection():
    """M3: missing numeric fields -> clean ProposalRejected, never KeyError."""
    from engine.proposal import validate_proposal, ProposalRejected
    cases = [
        {"element": "step", "zone_name": "Tempo"},                     # all missing
        {"element": "step", "duration_seconds": 600, "low_pct": 80},   # no high
        {"element": "step", "duration_seconds": 0, "low_pct": 80,
         "high_pct": 88, "zone_name": "Tempo"},                        # zero dur
    ]
    for st in cases:
        try:
            validate_proposal({"structural_pattern": "continuous",
                               "summary": "x", "main_set": [st]},
                              mode="power", dominant_zone="Tempo")
            assert False, f"expected rejection for {st}"
        except ProposalRejected:
            pass
        except KeyError:
            assert False, f"KeyError leaked for {st}"


def test_m3_missing_repeats_clean_rejection():
    from engine.proposal import validate_proposal, ProposalRejected
    bad = {"structural_pattern": "classic_interval", "summary": "no repeats",
           "main_set": [{"element": "repeat", "steps": [
               {"duration_seconds": 600, "low_pct": 80, "high_pct": 88,
                "zone_name": "Tempo"}]}]}
    try:
        validate_proposal(bad, mode="power", dominant_zone="Tempo")
        assert False, "expected rejection"
    except ProposalRejected:
        pass
    except KeyError:
        assert False, "KeyError leaked"


def test_m3_recovery_high_end_checked():
    """m3: a 'recovery' reaching 90% is not a recovery; the whole range must
    be easy, not just its low end."""
    from engine.proposal import validate_proposal, ProposalRejected
    bad = {"structural_pattern": "classic_interval", "summary": "hard recovery",
           "main_set": [{"element": "repeat", "repeats": 3, "steps": [
               {"duration_seconds": 600, "low_pct": 80, "high_pct": 88,
                "zone_name": "Tempo"},
               {"duration_seconds": 180, "low_pct": 80, "high_pct": 90,
                "zone_name": "Tempo", "is_recovery": True}]}]}
    try:
        validate_proposal(bad, mode="power", dominant_zone="Tempo")
        assert False, "expected rejection: recovery up to 90%"
    except ProposalRejected:
        pass


# ============================================================
# A4: rejection reason fed back to the next retry attempt
# ============================================================

def test_a4_feedback_reaches_second_attempt():
    """A4: the exact rejection reason must appear in the next attempt's user
    prompt, so the model corrects instead of guessing blind."""
    from engine.models import GenerationRequest
    from engine.generator_v2 import generate_single_v2

    prompts: list[str] = []

    def transport(system, user, tools, web):
        prompts.append(user)
        if len(prompts) == 1:  # first: zone-spill -> rejected (A1)
            return {"structural_pattern": "continuous", "summary": "bad",
                    "warmup_seconds": 300, "prep_seconds": 60,
                    "cooldown_seconds": 120,
                    "main_set": [{"element": "step", "duration_seconds": 1200,
                                  "low_pct": 75, "high_pct": 105,
                                  "zone_name": "Tempo"}]}
        return {"structural_pattern": "continuous", "summary": "fixed",
                "warmup_seconds": 300, "prep_seconds": 60,
                "cooldown_seconds": 120,
                "main_set": [{"element": "step", "duration_seconds": 1200,
                              "low_pct": 80, "high_pct": 88,
                              "zone_name": "Tempo"}]}

    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Tempo")
    sess = generate_single_v2(req, transport=transport)
    assert len(prompts) == 2
    assert "REJECTED" not in prompts[0]
    assert "REJECTED" in prompts[1] and "not contained" in prompts[1]
    assert sess.estimated_tss > 0


def test_a4_progression_feedback_reaches_retry():
    from engine.models import GenerationRequest
    from engine.generate_progression import generate_progression

    prompts: list[str] = []

    def transport(system, user, tools, web):
        prompts.append(user)
        good = {"structural_pattern": "continuous", "summary": "ok",
                "warmup_seconds": 300, "prep_seconds": 60,
                "cooldown_seconds": 120,
                "main_set": [{"element": "step", "duration_seconds": 1200,
                              "low_pct": 80, "high_pct": 88,
                              "zone_name": "Tempo"}]}
        if len(prompts) == 1:  # first: empty progression -> rejected
            return {"reasoning": "t", "sessions": []}
        return {"reasoning": "t", "graduation_note": None, "sessions": [good]}

    req = GenerationRequest(kind="progression", mode="power",
                            requested_zone="Tempo")
    result = generate_progression(req, transport=transport)
    assert len(prompts) == 2
    assert "REJECTED" in prompts[1] and "no sessions" in prompts[1]
    assert len(result.sessions) == 1


# ============================================================
# M4: zone-bounded conflict detection without a user IF
# ============================================================

def test_m4_tss_without_if_is_clean_conflict():
    """M4: 'TSS 100, max 20 min, Tempo' (no IF) must be a numeric conflict
    report BEFORE any API call — not a generic 'no valid proposal'."""
    from engine.models import GenerationRequest
    from engine.generator_v2 import generate_single_v2
    from engine.structure import ConstraintConflict

    def never_called(system, user, tools, web):
        raise AssertionError("transport must not be called on a conflict")

    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Tempo", target_tss=100,
                            max_available_seconds=1200)
    try:
        generate_single_v2(req, transport=never_called)
        assert False, "expected ConstraintConflict"
    except ConstraintConflict as e:
        # Concrete numbers: needed minutes and achievable TSS at zone top.
        assert "74.1 min" in e.report and "~27" in e.report


def test_m4_if_above_zone_ceiling_is_conflict():
    from engine.models import GenerationRequest
    from engine.generator_v2 import generate_single_v2
    from engine.structure import ConstraintConflict

    def never_called(system, user, tools, web):
        raise AssertionError("transport must not be called on a conflict")

    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Tempo", target_if=1.05)
    try:
        generate_single_v2(req, transport=never_called)
        assert False, "expected ConstraintConflict"
    except ConstraintConflict as e:
        assert "IF ceiling" in e.report


def test_m4_feasible_target_passes_to_generation():
    """Counterpart: a reachable TSS proceeds normally to the resolver."""
    from engine.models import GenerationRequest
    from engine.generator_v2 import generate_single_v2

    def mock(system, user, tools, web):
        return {"structural_pattern": "classic_interval", "summary": "ok",
                "warmup_seconds": 300, "prep_seconds": 120,
                "cooldown_seconds": 300,
                "main_set": [{"element": "repeat", "repeats": 3, "steps": [
                    {"duration_seconds": 600, "low_pct": 80, "high_pct": 88,
                     "zone_name": "Tempo"},
                    {"duration_seconds": 180, "low_pct": 55, "high_pct": 60,
                     "zone_name": "Endurance", "is_recovery": True}]}]}

    req = GenerationRequest(kind="single_session", mode="power",
                            requested_zone="Tempo", target_tss=55,
                            max_available_seconds=3600)
    sess = generate_single_v2(req, transport=mock)
    assert abs(sess.estimated_tss - 55) / 55 < 0.03


def test_m4_open_ended_zone_skips_ceiling_check():
    """Neuromuscular has no upper bound -> the ceiling check must not fire."""
    from engine.structure import check_zone_feasibility
    check_zone_feasibility("power", "Neuromuscular", 500, None, 600)  # no raise
