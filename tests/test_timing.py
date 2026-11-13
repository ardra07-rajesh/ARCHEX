import pytest

from app.simulation.timing.statistics import cohens_d, histogram, welch_t
from app.simulation.timing.timing_engine import TimingInputError, run_timing_experiment


def test_baseline_classes_are_distinguishable():
    r = run_timing_experiment({"samples": 2000, "seed": 1})
    b = r["baseline"]
    assert b["distinguishability"] > 0.95 and b["leakage_indicator"] == "high"
    assert b["class1_cached"]["mean"] < b["class0_uncached"]["mean"]
    assert abs(b["welch_t"]) > 20 and abs(b["cohens_d"]) > 5


def test_constant_time_defence_removes_distinguishability_at_a_cost():
    r = run_timing_experiment({"samples": 4000, "seed": 2, "defence": {"constant_time": True}})
    assert r["protected"]["distinguishability"] < 0.56 and r["protected"]["leakage_indicator"] == "low"
    assert r["comparison"]["mean_latency_overhead_pct"] > 50


def test_noise_and_flush_reduce_distinguishability_monotonically():
    d = lambda **k: run_timing_experiment({"samples": 4000, "seed": 3, "defence": k})["protected"]["distinguishability"]  # noqa: E731
    assert d(timing_noise_std=300) < d(timing_noise_std=0.0) + 1e-9
    assert d(flush_probability=0.5) < 0.95


def test_deterministic_and_validated():
    a = run_timing_experiment({"samples": 500, "seed": 7, "defence": {"timing_noise_std": 20}})
    assert a == run_timing_experiment({"samples": 500, "seed": 7, "defence": {"timing_noise_std": 20}})
    with pytest.raises(TimingInputError):
        run_timing_experiment({"samples": 10})
    with pytest.raises(TimingInputError):
        run_timing_experiment({"hit_latency_mean": 300, "miss_latency_mean": 200})


def test_statistics_helpers():
    assert welch_t([1, 2, 3], [1, 2, 3]) == 0
    assert cohens_d([10, 11, 12], [1, 2, 3]) > 5
    h = histogram([1, 2, 3], [4, 5, 6], bins=3)
    assert sum(x["class1"] + x["class0"] for x in h) == 6
