from fastapi import APIRouter, Query

from app.ai import pipeline
from app.simulation.benchmarks import run_benchmarks

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])


@router.get("")
def benchmarks(seed: int = Query(0, ge=0, le=1000)) -> dict:
    out = dict(run_benchmarks(seed))
    try:
        m = pipeline.evaluation_report()["metrics"]
        out["ai"] = {"available": True, "models": [
            {"model": "isolation_forest", **{k: m["isolation_forest"][k] for k in ("precision", "recall", "f1", "false_positive_rate", "roc_auc")}},
            {"model": "random_forest", **{k: m["random_forest"]["binary"][k] for k in ("precision", "recall", "f1", "false_positive_rate", "roc_auc")}},
            {"model": "logistic_regression", **{k: m["logistic_regression"]["binary"][k] for k in ("precision", "recall", "f1", "false_positive_rate", "roc_auc")}}]}
    except pipeline.ModelsNotTrained:
        out["ai"] = {"available": False, "models": [], "reason": "Models not trained (AI Detection Centre)."}
    return out
