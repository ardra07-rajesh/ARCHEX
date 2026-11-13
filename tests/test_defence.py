import pytest

from app.simulation.defence.comparison import DefenceInputError, compare_defences, run_config, PARAMS
from app.simulation.defence.countermeasures import NO_DEFENCE

Q = {**PARAMS, "rounds": 300}


def dist(**kw):
    return run_config({**NO_DEFENCE, **kw}, Q)["security"]["distinguishability"]


def test_baseline_is_clearly_distinguishable():
    assert dist() > 0.95


def test_cache_level_defences_remove_the_signal():
    for kw in ({"cache_partitioning": True}, {"memory_isolation": True}, {"cache_flushing": True}):
        assert dist(**kw) < 0.62, kw


def test_constant_time_alone_still_leaks_through_speculation():
    assert 0.65 < dist(constant_time=True) < 0.9
    assert dist(constant_time=True, speculation_restriction=True) < 0.62


def test_speculation_restriction_alone_leaves_architectural_channel():
    assert dist(speculation_restriction=True) > 0.9


def test_timing_noise_reduces_distinguishability_monotonically():
    a, b, c = dist(timing_noise_std=100), dist(timing_noise_std=600), dist(timing_noise_std=3000)
    assert a >= b - 0.03 and b > c - 0.03 and c < 0.75 < a + 0.3


def test_speculation_restriction_blocks_fills():
    base = run_config(NO_DEFENCE, Q)["security"]
    prot = run_config({**NO_DEFENCE, "speculation_restriction": True}, Q)["security"]
    assert base["speculative_cache_fills"] > 0 and prot["speculative_cache_fills"] == 0 and prot["speculative_loads_blocked"] > 0


def test_overheads_are_positive_and_baseline_is_zero():
    r = compare_defences({"cache_partitioning": True}, Q, include_recommendations=False)
    assert r["comparison"]["hit_ratio_protected"] < r["comparison"]["hit_ratio_baseline"] and r["comparison"]["overhead_pct"] > 0
    by = {s["defence"]: s for s in r["single_defences"]}
    assert all(s["overhead_pct"] > 0 for s in by.values())
    # speculation restriction cost is exactly branches * 3 cycles on an unchanged cache
    base = run_config(NO_DEFENCE, Q)["performance"]["cycles"]
    sr = run_config({**NO_DEFENCE, "speculation_restriction": True}, Q)["performance"]["cycles"]
    assert sr - base == (Q["perf_accesses"] + 4) // 5 * 3


def test_recommendations_are_grounded_in_reported_numbers():
    r = compare_defences({"constant_time": True}, Q)
    top = r["recommendations"][0]
    assert top["defence"] == "speculation_restriction"
    assert top["distinguishability_after"] < top["distinguishability_before"]
    assert f"{top['distinguishability_before']:.1%}" in top["why"] and f"{top['distinguishability_after']:.1%}" in top["why"]
    done = compare_defences({"cache_flushing": True}, Q)["recommendations"][0]
    assert done["defence"] is None and "noise floor" in done["why"]


def test_deterministic_and_validated():
    a = compare_defences({"cache_flushing": True}, {"rounds": 60}, False, False)
    assert a == compare_defences({"cache_flushing": True}, {"rounds": 60}, False, False)
    with pytest.raises(DefenceInputError):
        compare_defences(None, {"rounds": 5})
