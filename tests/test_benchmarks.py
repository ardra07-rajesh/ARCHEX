from app.simulation.benchmarks import run_benchmarks


def test_benchmark_suite_structure_and_content():
    r = run_benchmarks(0)
    assert r["data_source"] == "simulated" and len(r["cache"]) == 4 and len(r["branch"]) == 4
    by = {c["workload"]: {x["label"]: x for x in c["results"]} for c in r["cache"]}
    assert by["matrix_row"]["4-way LRU"]["l1_hit_ratio"] > by["matrix_col"]["4-way LRU"]["l1_hit_ratio"]
    assert all(len(c["results"]) == 6 for c in r["cache"])
    loop = {x["predictor"]: x for x in r["branch"][0]["results"]}
    assert loop["two_bit"]["mispredictions"] == 21 and loop["always_taken"]["mispredictions"] == 20  # 20 loop exits; 2-bit also misses once while warming up
    assert len(r["defence"]["singles"]) == 6 and r["defence"]["baseline_distinguishability"] > 0.95


def test_benchmarks_deterministic():
    assert run_benchmarks(3) == run_benchmarks(3)
