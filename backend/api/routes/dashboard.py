from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, select
from app.database.models import Experiment, ExperimentExecution, ActivityEvent, AnalysisRecord
from app.services.research import loads, result_summary

from app.core.events import bus
from app.database.repositories import analysis as repo
from app.database.session import get_db
from pydantic import BaseModel, Field

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class Kpi(BaseModel):
    key: str
    label: str
    unit: str
    value: float | None  # None = no data yet (never fabricated)
    source: str


class DashboardSummary(BaseModel):
    kpis: list[Kpi]
    recent_activity: list[dict]
    recent_experiments: list[dict] = Field(default_factory=list)
    recent_anomalies: list[dict] = Field(default_factory=list)
    defence_comparisons: list[dict] = Field(default_factory=list)
    execution_counts: dict[str, int] = Field(default_factory=dict)
    benchmark_summary: dict | None = None
    has_data: bool
    scope_note: str


def _pct(x: float | None) -> float | None:
    return None if x is None else round(x * 100, 2)


@router.get("/summary", response_model=DashboardSummary)
def summary(db: Session = Depends(get_db)) -> DashboardSummary:
    total, anomalous = repo.counts(db)
    # Persistent experiment and execution records are the primary source; legacy lab events remain session-scoped.
    scoped = bool(db.info.get("user_id") and db.info.get("user_role") != "admin")
    owned_ids = select(Experiment.id).where(Experiment.owner_id == db.info["user_id"]) if scoped else None
    experiment_count = select(func.count()).select_from(Experiment)
    if scoped: experiment_count = experiment_count.where(Experiment.owner_id == db.info["user_id"])
    total_experiments = int(db.scalar(experiment_count) or 0)
    execution_counts = {status: int(db.scalar(select(func.count()).select_from(ExperimentExecution).where(ExperimentExecution.status == status, *([ExperimentExecution.experiment_id.in_(owned_ids)] if scoped else []))) or 0)
                        for status in ("completed", "failed", "running")}
    active_executions = execution_counts["running"]
    latest_stmt = select(Experiment).where(Experiment.result_json.is_not(None)).order_by(Experiment.updated_at.desc()).limit(20)
    if scoped: latest_stmt = select(Experiment).where(Experiment.owner_id == db.info["user_id"], Experiment.result_json.is_not(None)).order_by(Experiment.updated_at.desc()).limit(20)
    latest_rows = db.scalars(latest_stmt).all()
    latest = {}
    for row in latest_rows:
        result = result_summary(row.result_json)
        if row.simulation == "cache" and "Cache" not in latest:
            latest["Cache"] = {"hierarchy_hit_ratio": result.get("summary.hierarchy_hit_ratio")}
        elif row.simulation == "branch" and "Branch" not in latest:
            latest["Branch"] = {"accuracy": result.get("run.metrics.accuracy")}
        elif row.simulation == "cpu" and "CPU" not in latest:
            latest["CPU"] = {"cycles": result.get("metrics.cycles")}
    s = bus.summary() if not db.info.get("user_id") else {"latest": {}}
    legacy_runs = [e for e in bus.recent(1000) if e["data"].get("experiment") and not e["data"].get("experiment_id") and e["category"] != "AI"] if not db.info.get("user_id") else []
    # Direct lab requests remain session-scoped until explicitly saved; workbench executions are already persistent.
    for category, data in s["latest"].items():
        latest.setdefault(category, data)
    ran = total_experiments + len(legacy_runs)
    spec = [
        ("experiments", "Total Experiments", "count", float(ran), "Saved experiments plus unsaved direct-lab runs this session"),
        ("active_sims", "Active Simulations", "count", float(active_executions), "Persisted execution records currently marked running"),
        ("cache_hit_ratio", "Cache Hit Ratio", "%", _pct(latest.get("Cache", {}).get("hierarchy_hit_ratio")), "Latest Cache Lab run"),
        ("branch_accuracy", "Branch Prediction Accuracy", "%", _pct(latest.get("Branch", {}).get("accuracy")), "Latest Branch run"),
        ("anomalies", "AI Anomalies Detected", "count", float(anomalous) if total else None, f"AI Detection Centre ({total} stored analyses)"),
        ("cycles", "Current Simulation Cycles", "cycles", float(latest["CPU"]["cycles"]) if "CPU" in latest else None, "Latest Architecture Studio run"),
    ]
    recent_stmt = select(ActivityEvent).order_by(ActivityEvent.id.desc()).limit(8)
    if scoped: recent_stmt = select(ActivityEvent).where(ActivityEvent.experiment_id.in_(owned_ids)).order_by(ActivityEvent.id.desc()).limit(8)
    recent = [{"id": e.id, "ts": e.created_at, "category": e.category, "severity": e.severity, "message": e.message}
              for e in db.scalars(recent_stmt).all()]
    if not db.info.get("user_id"):
        recent.extend({"id": f"session-{e['id']}", "ts": e["ts"], "category": e["category"], "severity": e["severity"], "message": e["message"]}
                      for e in bus.recent(100) if not e["data"].get("experiment_id"))
    recent.sort(key=lambda e: e["ts"], reverse=True)
    recent_exp_stmt = select(Experiment).order_by(Experiment.updated_at.desc()).limit(6)
    if scoped: recent_exp_stmt = select(Experiment).where(Experiment.owner_id == db.info["user_id"]).order_by(Experiment.updated_at.desc()).limit(6)
    recent_experiments = db.scalars(recent_exp_stmt).all()
    anomaly_stmt = select(AnalysisRecord).where(AnalysisRecord.classification == "anomalous")
    if scoped: anomaly_stmt = anomaly_stmt.where(AnalysisRecord.owner_id == db.info["user_id"])
    recent_anomalies = db.scalars(anomaly_stmt
                                  .order_by(AnalysisRecord.id.desc()).limit(5)).all()
    defence_stmt = select(ActivityEvent).where(ActivityEvent.category == "Defence").order_by(ActivityEvent.id.desc()).limit(4)
    if scoped: defence_stmt = select(ActivityEvent).where(ActivityEvent.category == "Defence", ActivityEvent.experiment_id.in_(owned_ids)).order_by(ActivityEvent.id.desc()).limit(4)
    defence_rows = db.scalars(defence_stmt).all()
    defence_comparisons = [{"id":e.id,"created_at":e.created_at,"message":e.message,"severity":e.severity} for e in defence_rows]
    if not db.info.get("user_id"):
        defence_comparisons.extend({"id":f"session-{e['id']}","created_at":e["ts"],"message":e["message"],"severity":e["severity"]}
                                   for e in bus.recent(100) if e["category"] == "Defence" and not e["data"].get("experiment_id"))
    benchmark_stmt = select(Experiment).where(Experiment.simulation == "benchmark", Experiment.status == "completed")
    if scoped: benchmark_stmt = benchmark_stmt.where(Experiment.owner_id == db.info["user_id"])
    benchmark = db.scalars(benchmark_stmt.order_by(Experiment.updated_at.desc()).limit(1)).first()
    benchmark_summary = {"name":benchmark.name,"updated_at":benchmark.updated_at,"metrics":result_summary(benchmark.result_json)} if benchmark else None
    return DashboardSummary(
        kpis=[Kpi(key=k, label=l, unit=u, value=v, source=src) for k, l, u, v, src in spec],
        recent_activity=recent[:8],
        recent_experiments=[{"id":e.id,"name":e.name,"simulation":e.simulation,"status":e.status,"updated_at":e.updated_at} for e in recent_experiments],
        recent_anomalies=[{"id":e.id,"created_at":e.created_at,"scenario":e.scenario,"classification":e.classification,"anomaly_score":e.anomaly_score} for e in recent_anomalies],
        defence_comparisons=defence_comparisons[:4],
        execution_counts=execution_counts,
        benchmark_summary=benchmark_summary,
        has_data=total > 0 or ran > 0,
        scope_note="Workbench experiment records and executions are persistent. Direct lab runs remain session-scoped until saved; AI analyses are stored in the database.",
    )
