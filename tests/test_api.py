from fastapi.testclient import TestClient

from app.core.events import bus
from app.main import app

client = TestClient(app)


def test_health_reports_real_component_states():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["components"]["api"]["status"] == "online"
    assert body["components"]["database"]["status"] == "online"
    assert body["components"]["simulation_engine"]["status"] == "online"
    # Unbuilt or untrained modules must never claim to be online.
    assert body["components"]["ai_service"]["status"] == "unavailable"


def test_dashboard_summary_has_no_fabricated_data():
    bus.clear()
    r = client.get("/api/v1/dashboard/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["has_data"] is False
    assert len(body["kpis"]) == 6
    assert body["recent_activity"] == []
    k = {x["key"]: x["value"] for x in body["kpis"]}
    assert k["experiments"] == 0 and k["cache_hit_ratio"] is None and k["branch_accuracy"] is None and k["cycles"] is None


def test_dashboard_reflects_real_runs():
    bus.clear()
    sim = client.post("/api/v1/architecture/simulate", json={"program": "ADDI R1, R0, 3\nHALT"}).json()
    cache = client.post("/api/v1/cache/simulate", json={"levels": [{"size_bytes": 1024, "block_size": 32, "associativity": 2}], "workload": {"pattern": "sequential", "count": 64}}).json()
    branch = client.post("/api/v1/speculation/simulate", json={}).json()
    body = client.get("/api/v1/dashboard/summary").json()
    k = {x["key"]: x["value"] for x in body["kpis"]}
    assert body["has_data"] is True and k["experiments"] == 3
    assert k["cycles"] == sim["metrics"]["cycles"]
    assert k["cache_hit_ratio"] == round(cache["summary"]["hierarchy_hit_ratio"] * 100, 2)
    assert k["branch_accuracy"] == round(branch["run"]["metrics"]["accuracy"] * 100, 2)
    assert [e["category"] for e in body["recent_activity"]] == ["Branch", "Cache", "CPU"]  # newest first


def test_failed_simulation_is_not_counted_as_an_experiment():
    bus.clear()
    assert client.post("/api/v1/architecture/simulate", json={"program": "FOO R1"}).status_code == 422
    assert bus.summary()["experiments"] == 0


def test_unhandled_error_returns_json_envelope_without_leaking_details():
    @app.get("/api/v1/__test_boom")
    def boom():
        raise RuntimeError("secret internal detail")

    r = TestClient(app, raise_server_exceptions=False).get("/api/v1/__test_boom")
    assert r.status_code == 500
    assert r.json()["detail"]["code"] == "internal_error" and "secret" not in r.text


def test_architecture_simulate_endpoint():
    r = client.post("/api/v1/architecture/simulate", json={"program": "ADDI R1, R0, 3\nADD R2, R1, R1\nHALT"})
    assert r.status_code == 200
    assert r.json()["final_registers"][2] == 6


def test_architecture_rejects_bad_program_with_line_numbers():
    r = client.post("/api/v1/architecture/simulate", json={"program": "ADDI R1, R0, 3\nFOO R1"})
    assert r.status_code == 422
    assert r.json()["detail"]["errors"][0]["line"] == 2


def test_architecture_rejects_out_of_range_config():
    r = client.post("/api/v1/architecture/simulate", json={"program": "HALT", "max_cycles": 1})
    assert r.status_code == 422


def test_workloads_listed():
    assert "loop_sum" in client.get("/api/v1/architecture/workloads").json()


def test_cache_simulate_endpoint_and_validation():
    body = {"levels": [{"size_bytes": 1024, "block_size": 32, "associativity": 2}], "workload": {"pattern": "sequential", "count": 64}}
    r = client.post("/api/v1/cache/simulate", json=body)
    assert r.status_code == 200 and r.json()["levels"][0]["accesses"] == 64
    bad = {"levels": [{"size_bytes": 1000, "block_size": 32}]}
    r = client.post("/api/v1/cache/simulate", json=bad)
    assert r.status_code == 422 and r.json()["detail"]["errors"]


def test_cache_compare_uses_same_workload():
    lv = lambda m: [{"size_bytes": 256, "block_size": 16, "mapping": m, "associativity": 2}]  # noqa: E731
    body = {"configs": [{"label": "dm", "levels": lv("direct")}, {"label": "fa", "levels": lv("fully_associative")}],
            "workload": {"pattern": "random", "count": 500, "working_set_bytes": 1024}, "seed": 3}
    r = client.post("/api/v1/cache/compare", json=body).json()
    assert len(r["results"]) == 2 and r["workload"]["accesses"] == 500


def test_events_rest_and_websocket():
    bus.clear()
    client.post("/api/v1/architecture/simulate", json={"program": "HALT"})
    evs = client.get("/api/v1/events").json()["events"]
    assert any(e["category"] == "CPU" for e in evs)
    with client.websocket_connect("/api/v1/ws/events") as ws:
        first = ws.receive_json()
        assert first["type"] == "backlog" and first["live"] is False


def test_speculation_endpoint():
    r = client.post("/api/v1/speculation/simulate", json={"predictor": "two_bit", "speculation": {}})
    assert r.status_code == 200 and len(r.json()["comparison"]) == 4 and r.json()["speculation"]["speculation_allowed"]
    assert client.post("/api/v1/speculation/simulate", json={}).json()["speculation"] is None  # speculation is opt-in
    bad = client.post("/api/v1/speculation/simulate", json={"workload": {"kind": "explicit", "outcomes": "TQ"}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_input"


def test_side_channel_endpoint():
    r = client.post("/api/v1/side-channel/simulate", json={"samples": 500, "defence": {"constant_time": True}})
    body = r.json()
    assert r.status_code == 200 and body["comparison"] is not None
    assert body["protected"]["distinguishability"] < body["baseline"]["distinguishability"]
    assert client.post("/api/v1/side-channel/simulate", json={"samples": 500}).json()["protected"] is None
    bad = client.post("/api/v1/side-channel/simulate", json={"hit_latency_mean": 50, "miss_latency_mean": 10})
    assert bad.status_code == 422 and bad.json()["detail"]["errors"]


def test_ai_flow_not_trained_then_trained():
    assert client.get("/api/v1/health").json()["components"]["ai_service"]["status"] == "unavailable"
    r = client.post("/api/v1/ai/analyze", json={"scenario": "normal"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "models_not_trained"
    assert client.post("/api/v1/ai/train", json={"n_per_class": 30, "n_test_per_class": 30}).status_code == 200
    r = client.post("/api/v1/ai/analyze", json={"scenario": "cache_contention", "seed": 4})
    assert r.status_code == 200 and r.json()["record_id"] >= 1
    assert client.get("/api/v1/ai/evaluation").json()["metrics"]["isolation_forest"]["roc_auc"] > 0.5
    assert len(client.get("/api/v1/ai/records").json()) >= 1
    assert client.get(f"/api/v1/ai/records/{r.json()['record_id']}").json()["explanation"]["detector"]["contributions"]
    assert client.get("/api/v1/ai/records/99999").status_code == 404
    assert client.get("/api/v1/health").json()["components"]["ai_service"]["status"] == "online"
    assert client.get("/api/v1/dashboard/summary").json()["has_data"] is True


def test_defence_and_benchmark_endpoints():
    r = client.post("/api/v1/defence/compare", json={"defences": {"cache_flushing": True}, "rounds": 60, "include_singles": False, "include_recommendations": False})
    assert r.status_code == 200 and r.json()["comparison"]["distinguishability_protected"] < 0.9
    assert client.post("/api/v1/defence/compare", json={"rounds": 5}).status_code == 422
    b = client.get("/api/v1/benchmarks").json()
    assert len(b["cache"]) == 4 and b["ai"]["available"] in (True, False)


def test_openapi_exposes_core_research_and_phase10_routes():
    schema = client.get("/api/v1/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    expected = {
        "/api/v1/health",
        "/api/v1/dashboard/summary",
        "/api/v1/architecture/simulate",
        "/api/v1/cache/simulate",
        "/api/v1/speculation/simulate",
        "/api/v1/side-channel/simulate",
        "/api/v1/ai/analyze",
        "/api/v1/defence/compare",
        "/api/v1/research/experiments",
        "/api/v1/reports",
    }
    assert expected.issubset(paths.keys())
