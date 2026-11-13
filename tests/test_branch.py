import pytest

from app.simulation.branch.predictors import run_predictor
from app.simulation.branch.speculation import run_speculation
from app.simulation.branch.workloads import BranchInputError, generate_branches


def loop(n=10, r=5):
    return generate_branches({"kind": "loop", "loop_iterations": n, "repeats": r}, 0)


def test_loop_predictor_misprediction_counts():
    seq = loop()
    mis = {k: run_predictor(k, seq)["metrics"]["mispredictions"] for k in ("always_taken", "always_not_taken", "one_bit", "two_bit")}
    assert mis == {"always_taken": 5, "always_not_taken": 45, "one_bit": 10, "two_bit": 6}


def test_alternating_defeats_counters():
    seq = generate_branches({"kind": "alternating", "count": 20}, 0)
    assert run_predictor("one_bit", seq)["metrics"]["accuracy"] == 0.0
    assert run_predictor("always_taken", seq)["metrics"]["accuracy"] == 0.5


def test_cycles_model_and_history():
    r = run_predictor("two_bit", loop(), penalty=3)
    m = r["metrics"]
    assert m["simulated_cycles"] == m["branches"] + m["mispredictions"] * 3 and m["flush_events"] == m["mispredictions"]
    assert r["steps"][0]["state_before"] == 1 and r["steps"][0]["predicted"] is False and r["steps"][0]["state_after"] == 2


def test_aliasing_hurts_when_branches_behave_oppositely():
    seq = [(4, True), (8, False)] * 20  # one always-taken and one never-taken branch
    separate = run_predictor("two_bit", seq, table_size=16)["metrics"]["mispredictions"]
    shared = run_predictor("two_bit", seq, table_size=1)["metrics"]["mispredictions"]
    assert separate == 1 and shared == 40


def test_explicit_validation_and_seed():
    with pytest.raises(BranchInputError):
        generate_branches({"kind": "explicit", "outcomes": "TXN"}, 0)
    a = generate_branches({"kind": "biased_random", "count": 100, "p_taken": 0.8}, 4)
    assert a == generate_branches({"kind": "biased_random", "count": 100, "p_taken": 0.8}, 4)


SP = {"window": 8, "spec_loads": 2, "loads_per_branch": 1, "working_set_bytes": 256, "cache_size_bytes": 256, "block_size": 32, "associativity": 8}


def test_speculation_leaves_residue_and_pollutes_cache():
    steps = run_predictor("one_bit", loop())["steps"]
    r = run_speculation(steps, SP, 0)
    allowed, restricted = r["speculation_allowed"], r["speculation_restricted"]
    assert allowed["speculative_cache_fills"] > 0 and allowed["residual_lines_in_cache"] > 0
    assert restricted["speculative_cache_fills"] == 0 and restricted["residual_lines_in_cache"] == 0
    assert allowed["squashed_instructions"] == restricted["squashed_instructions"] > 0
    assert restricted["correct_path_hit_ratio"] > allowed["correct_path_hit_ratio"]
    assert r["hit_ratio_cost_of_speculation"] > 0


def test_no_mispredictions_means_no_speculative_side_effects():
    steps = run_predictor("always_taken", generate_branches({"kind": "explicit", "outcomes": "TTTTTT"}, 0))["steps"]
    r = run_speculation(steps, SP, 0)
    assert r["speculation_allowed"]["speculative_cache_fills"] == 0 and r["hit_ratio_cost_of_speculation"] == 0
