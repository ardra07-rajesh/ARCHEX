from fastapi.testclient import TestClient

from app.main import app
from app.simulation.advanced.engine import run_advanced_predictor

client = TestClient(app)


def test_gshare_and_tournament_are_deterministic_and_bounded():
    seq = [(4, True), (8, False), (4, True), (8, False)] * 20
    for kind in ("gshare", "tournament"):
        first = run_advanced_predictor(kind, seq, 256, 8)
        second = run_advanced_predictor(kind, seq, 256, 8)
        assert first == second
        assert first["metrics"]["branches"] == len(seq)
        assert 0 <= first["metrics"]["accuracy"] <= 1


def test_advanced_branch_endpoint():
    response = client.post("/api/v1/advanced/branch-predictor", json={
        "predictor": "gshare", "workload": {"kind": "nested_loops", "outer": 4, "inner": 3},
        "table_size": 256, "history_bits": 8, "seed": 17,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["data_source"] == "simulated"
    assert body["metrics"]["branches"] == 16
    assert len(body["trace"]) == 16


def test_advanced_branch_rejects_invalid_history_configuration():
    response = client.post("/api/v1/advanced/branch-predictor", json={"table_size": 32, "history_bits": 8})
    assert response.status_code == 422


def test_shared_cache_contention_endpoint_has_isolated_baseline():
    response = client.post("/api/v1/advanced/cache-contention", json={
        "cores": 3, "accesses_per_core": 128, "pattern": "hot_cold", "working_set_bytes": 2048,
        "cache_size_bytes": 4096, "block_size": 64, "associativity": 4, "seed": 9,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["accesses"] == 384
    assert len(body["per_core_shared"]) == 3
    assert len(body["per_core_isolated"]) == 3
    assert body["summary"]["flush_on_switch_misses"] >= body["summary"]["shared_misses"]
    assert body["summary"]["partitioned_llc_misses"] >= 0
    assert body["data_source"] == "simulated"


def test_multi_seed_statistics_are_reproducible_and_ordered():
    payload = {"predictor": "tournament", "workload": {"kind": "biased_random", "count": 80, "p_taken": 0.7},
               "table_size": 256, "history_bits": 8, "seeds": [1, 2, 3, 4]}
    first = client.post("/api/v1/advanced/multi-seed-evaluation", json=payload)
    second = client.post("/api/v1/advanced/multi-seed-evaluation", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["statistics"]["n"] == 4


def test_matrix_contention_keeps_requested_access_count():
    response = client.post("/api/v1/advanced/cache-contention", json={
        "cores": 2, "accesses_per_core": 100, "pattern": "matrix_row", "working_set_bytes": 2048,
        "cache_size_bytes": 4096, "block_size": 64, "associativity": 4, "seed": 3,
    })
    assert response.status_code == 200
    assert response.json()["summary"]["accesses"] == 200


def test_multi_seed_rejects_duplicate_seeds():
    response = client.post("/api/v1/advanced/multi-seed-evaluation", json={
        "predictor": "gshare", "seeds": [7, 7],
    })
    assert response.status_code == 422


def test_advanced_routes_are_in_openapi_contract():
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    assert "/api/v1/advanced/branch-predictor" in paths
    assert "/api/v1/advanced/cache-contention" in paths
    assert "/api/v1/advanced/multi-seed-evaluation" in paths
