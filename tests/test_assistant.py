from fastapi.testclient import TestClient
from app.main import app
from app.core.events import bus
from app.database.session import SessionLocal
from app.database.models import AnalysisRecord
import json

client = TestClient(app)

def test_assistant_status_does_not_expose_secret():
    response = client.get("/api/v1/assistant/status")
    assert response.status_code == 200
    body = response.json()
    assert "api_key_configured" in body and "api_key" not in body

def test_conversation_persistence_and_local_fallback():
    created = client.post("/api/v1/assistant/conversations", json={"title": "Cache research"})
    assert created.status_code == 200
    cid = created.json()["id"]
    reply = client.post(f"/api/v1/assistant/conversations/{cid}/messages", json={"message": "What factors influence cache miss rate?"})
    assert reply.status_code == 200, reply.text
    assert "cache" in reply.json()["content"].lower()
    history = client.get(f"/api/v1/assistant/conversations/{cid}").json()
    assert len(history["messages"]) == 2
    assert history["messages"][0]["role"] == "user"
    assert history["messages"][1]["role"] == "assistant"
    assert client.delete(f"/api/v1/assistant/conversations/{cid}").json()["deleted"] is True
    assert client.get(f"/api/v1/assistant/conversations/{cid}").status_code == 404

def test_assistant_uses_selected_saved_analysis_context():
    with SessionLocal() as db:
        row = AnalysisRecord(created_at="2026-11-10T00:00:00+00:00", scenario="cache_contention", seed=7,
            classification="anomalous", anomaly_score=0.81, result_json=json.dumps({"trace":{"accesses":120},"features":{"cache_miss_rate":0.4},"detection":{"classification":"anomalous"}}))
        db.add(row); db.commit(); db.refresh(row); record_id = row.id
    conv = client.post("/api/v1/assistant/conversations", json={}).json()
    reply = client.post(f"/api/v1/assistant/conversations/{conv['id']}/messages", json={"message":"Summarise this record", "context_analysis_id":record_id})
    assert reply.status_code == 200
    assert f"#{record_id}" in reply.json()["content"]
    history = client.get(f"/api/v1/assistant/conversations/{conv['id']}").json()
    assert history["messages"][0]["context"]["record"]["anomaly_score"] == 0.81


def test_health_reports_local_assistant_fallback_as_available():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["components"]["assistant"]["status"] == "online"
