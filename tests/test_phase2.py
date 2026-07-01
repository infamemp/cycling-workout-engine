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
