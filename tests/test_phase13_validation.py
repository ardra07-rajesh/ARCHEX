import hashlib
import json

from fastapi.testclient import TestClient

from app.main import app
from app.simulation.benchmarks import run_benchmarks_fresh

client = TestClient(app)

def test_validation_catalog_is_explicit_about_simulation():
    response = client.get("/api/v1/validation/catalog")
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_source"] == "simulated"
    assert payload["methodology"]["hardware_measurements"] is False
    assert len(payload["workloads"]) >= 8

def test_fresh_benchmark_results_are_deterministic():
    a = run_benchmarks_fresh(23)
    b = run_benchmarks_fresh(23)
    canonical = lambda x: json.dumps(x, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(canonical(a)).hexdigest() == hashlib.sha256(canonical(b)).hexdigest()

def test_validation_run_persists_manifest_and_reproduces():
    created = client.post("/api/v1/validation/runs", json={"seed": 19})
    assert created.status_code == 200
    payload = created.json()
    assert payload["manifest"]["seed"] == 19
    assert payload["manifest"]["result_sha256"] == payload["result_sha256"]
    assert payload["manifest"]["deterministic"] is True
    listed = client.get("/api/v1/validation/runs")
    assert listed.status_code == 200
    assert any(x["id"] == payload["id"] for x in listed.json())
    replay = client.post(f"/api/v1/validation/runs/{payload['id']}/reproduce")
    assert replay.status_code == 200
    assert replay.json()["reproducible"] is True


def test_ai_training_exposes_split_provenance():
    from app.ai.pipeline import train_all
    bundle = train_all(n_per_class=30, n_test_per_class=30, seed=7, save=False)
    manifest = bundle["split_manifest"]
    assert manifest["seed_ranges_disjoint"] is True
    assert manifest["scaler_fit_partition"] == "train_only"
    assert manifest["train_samples"] == 120
    assert manifest["test_samples"] == 120
    assert len(manifest["split_fingerprint_sha256"]) == 64
