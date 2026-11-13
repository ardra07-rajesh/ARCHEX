import csv
import io
import json
from sqlalchemy import delete
from fastapi.testclient import TestClient
from app.main import app
from app.database.session import SessionLocal
from app.database.models import Experiment, ExperimentExecution, ActivityEvent, ResearchReport

client = TestClient(app)


def _clear():
    with SessionLocal() as db:
        for model in (ResearchReport, ExperimentExecution, ActivityEvent, Experiment):
            db.execute(delete(model))
        db.commit()


def _completed_experiment():
    _clear()
    body={"name":"Phase 9 CPU report evidence","description":"Validate a small CPU pipeline workload.",
          "category":"cpu","simulation":"cpu","config":{"program":"ADDI R1, R0, 9\nHALT","num_registers":8,
          "forwarding":True,"max_cycles":2000,"memory_size_words":256,"clock_mhz":100},"tags":["report-test"]}
    created=client.post("/api/v1/research/experiments",json=body)
    assert created.status_code==200,created.text
    run=client.post(f"/api/v1/research/experiments/{created.json()['id']}/run")
    assert run.status_code==200,run.text
    return created.json()


def test_phase9_generates_and_downloads_pdf_csv_json_from_saved_experiment():
    experiment=_completed_experiment()
    generated=[]
    for fmt in ("pdf","csv","json"):
        response=client.post("/api/v1/reports/generate",json={"experiment_id":experiment["id"],"format":fmt})
        assert response.status_code==200,response.text
        record=response.json(); generated.append(record)
        assert record["status"]=="completed" and record["file_size"]>0
        download=client.get(f"/api/v1/reports/{record['id']}/download")
        assert download.status_code==200
        assert len(download.content)>0
        if fmt=="pdf": assert download.content.startswith(b"%PDF-")
        if fmt=="csv":
            text=download.content.decode("utf-8-sig")
            assert "experiment_metric" in text and experiment["id"] in text
        if fmt=="json":
            payload=json.loads(download.content)
            assert payload["experiment"]["id"]==experiment["id"]
            assert payload["executions"]
            assert "not physical hardware measurements" in payload["data_provenance"]
        preview=client.get(f"/api/v1/reports/{record['id']}/preview")
        assert preview.status_code==200
        if fmt=="pdf":
            assert preview.json()["preview_mode"]=="inline_document"
            inline=client.get(f"/api/v1/reports/{record['id']}/download?disposition=inline")
            assert inline.status_code==200 and "inline" in inline.headers.get("content-disposition","")
        else: assert preview.json()["content"]
    history=client.get("/api/v1/reports",params={"experiment_id":experiment["id"]})
    assert history.status_code==200 and history.json()["total"]==3
    assert client.delete(f"/api/v1/reports/{generated[0]['id']}").json()["deleted"] is True
    assert client.get(f"/api/v1/reports/{generated[0]['id']}").status_code==404


def test_phase9_rejects_missing_experiment_and_invalid_sections():
    missing=client.post("/api/v1/reports/generate",json={"experiment_id":"missing","format":"pdf"})
    assert missing.status_code==404
    exp=_completed_experiment()
    invalid=client.post("/api/v1/reports/generate",json={"experiment_id":exp["id"],"format":"pdf","sections":["made_up"]})
    assert invalid.status_code==422


def test_phase9_report_sections_can_be_customised():
    exp=_completed_experiment()
    response=client.post("/api/v1/reports/generate",json={"experiment_id":exp["id"],"format":"json",
        "title":"Minimal evidence export","sections":["executive_summary","results"],"detail_level":"concise"})
    assert response.status_code==200,response.text
    payload=client.get(f"/api/v1/reports/{response.json()['id']}/download").json()
    assert payload["sections"]==["executive_summary","results"]
    assert payload["detail_level"]=="concise"
