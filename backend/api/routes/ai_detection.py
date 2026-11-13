from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai import pipeline
from app.core.events import bus
from app.database.repositories import analysis as repo
from app.database.session import get_db
from app.simulation.timing.trace_generator import LABELS, SCENARIOS

router = APIRouter(prefix="/ai", tags=["ai"])


class TrainRequest(BaseModel):
    n_per_class: int = Field(300, ge=30, le=1000)
    n_test_per_class: int = Field(150, ge=30, le=500)
    seed: int = Field(0, ge=0, le=100)


class AnalyzeRequest(BaseModel):
    scenario: Literal["normal", "cache_contention", "timing_probe", "branch_mistraining"] = "normal"
    seed: int = Field(0, ge=0, le=10**9)
    classifier: Literal["random_forest", "logistic_regression"] = "random_forest"


def _need_models():
    try:
        return pipeline.load_bundle()
    except pipeline.ModelsNotTrained as e:
        raise HTTPException(409, detail={"code": "models_not_trained", "message": str(e), "errors": []}) from e


@router.post("/train")
def train(req: TrainRequest) -> dict:
    b = pipeline.train_all(req.n_per_class, req.n_test_per_class, req.seed, save=True)
    bus.publish("AI", f"Models trained on {b['config']['n_train']} synthetic traces, evaluated on {b['config']['n_test']}", data={"seed": req.seed})
    return {"status": "trained", "trained_at": b["trained_at"], "config": b["config"]}


@router.post("/analyze")
def analyze(req: AnalyzeRequest, db: Session = Depends(get_db)) -> dict:
    _need_models()
    result = pipeline.analyze(req.scenario, req.seed, req.classifier)
    record_id = repo.save(db, result)
    d = result["detection"]
    bus.publish("AI", f"Analysed {req.scenario} trace (seed {req.seed}): {d['classification']}, anomaly score {d['anomaly_score']:.3f}",
                "warning" if d["classification"] == "anomalous" else "info",
                {"experiment": True, "record_id": record_id, "classification": d["classification"]})
    return {"record_id": record_id, **result}


@router.get("/evaluation")
def evaluation() -> dict:
    _need_models()
    return pipeline.evaluation_report()


@router.get("/scenarios")
def scenarios() -> dict:
    return {s: LABELS[s] for s in SCENARIOS}


@router.get("/records")
def records(limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    return repo.list_recent(db, max(1, min(limit, 200)))


@router.get("/records/{record_id}")
def record(record_id: int, db: Session = Depends(get_db)) -> dict:
    r = repo.get(db, record_id)
    if r is None:
        raise HTTPException(404, detail={"code": "not_found", "message": f"Analysis record {record_id} not found", "errors": []})
    return r
