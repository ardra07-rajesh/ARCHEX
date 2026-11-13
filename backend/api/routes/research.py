import json
import uuid
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database.models import Experiment, ExperimentExecution, ActivityEvent
from app.core.events import bus
from app.database.session import get_db
from app.services.research import (dumps, loads, now, experiment_dict, execution_dict,
                                   execute_and_persist, flatten_metrics, record_event, load_result, delete_result_artifact)

router = APIRouter(prefix="/research", tags=["research"])


class ExperimentInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field("", max_length=4000)
    category: str = Field("microarchitecture", max_length=40)
    simulation: Literal["cpu", "cache", "branch", "speculation", "side_channel", "defence", "benchmark"]
    config: dict
    notes: str = Field("", max_length=12000)
    tags: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("config")
    @classmethod
    def config_size_limit(cls, value: dict) -> dict:
        if len(json.dumps(value, ensure_ascii=False)) > 256_000:
            raise ValueError("Experiment configuration must be 256 KB or smaller")
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        cleaned = [tag.strip() for tag in value]
        if any(not tag or len(tag) > 40 for tag in cleaned):
            raise ValueError("Tags must contain 1–40 non-whitespace characters")
        return cleaned


class ExperimentPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=160)
    description: str | None = Field(None, max_length=4000)
    notes: str | None = Field(None, max_length=12000)
    tags: list[str] | None = Field(None, max_length=30)
    config: dict | None = None
    category: str | None = Field(None, max_length=40)
    simulation: Literal["cpu", "cache", "branch", "speculation", "side_channel", "defence", "benchmark"] | None = None

    @field_validator("config")
    @classmethod
    def config_size_limit(cls, value: dict | None) -> dict | None:
        if value is not None and len(json.dumps(value, ensure_ascii=False)) > 256_000:
            raise ValueError("Experiment configuration must be 256 KB or smaller")
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        cleaned = [tag.strip() for tag in value]
        if any(not tag or len(tag) > 40 for tag in cleaned):
            raise ValueError("Tags must contain 1–40 non-whitespace characters")
        return cleaned


def _get(db: Session, experiment_id: str) -> Experiment:
    row = db.get(Experiment, experiment_id)
    if row is not None and db.info.get("user_id") and db.info.get("user_role") != "admin" and row.owner_id != db.info.get("user_id"):
        row = None
    if row is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Experiment not found", "errors": []})
    return row


@router.post("/experiments")
def create_experiment(req: ExperimentInput, db: Session = Depends(get_db)):
    ts = now()
    row = Experiment(id=str(uuid.uuid4()), name=req.name, description=req.description, category=req.category,
                     simulation=req.simulation, created_at=ts, updated_at=ts, status="draft",
                     config_json=dumps(req.config), notes=req.notes, tags_json=dumps(req.tags), owner_id=db.info.get("user_id"))
    db.add(row); db.commit(); db.refresh(row)
    record_event(db, "Research", f"Experiment {row.name} created", experiment_id=row.id)
    return experiment_dict(row)


@router.get("/experiments")
def list_experiments(q: str = Query("", max_length=160), category: str | None = None,
                     simulation: str | None = None, status: str | None = None, tag: str | None = None,
                     sort: Literal["created_at", "updated_at", "name"] = "updated_at",
                     order: Literal["asc", "desc"] = "desc", limit: int = Query(50, ge=1, le=200),
                     offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    stmt = select(Experiment)
    count_stmt = select(func.count()).select_from(Experiment)
    if db.info.get("user_id") and db.info.get("user_role") != "admin":
        stmt = stmt.where(Experiment.owner_id == db.info["user_id"])
        count_stmt = count_stmt.where(Experiment.owner_id == db.info["user_id"])
    if q:
        term = f"%{q}%"
        stmt = stmt.where(or_(Experiment.name.ilike(term), Experiment.description.ilike(term)))
    if category: stmt = stmt.where(Experiment.category == category)
    if simulation: stmt = stmt.where(Experiment.simulation == simulation)
    if status: stmt = stmt.where(Experiment.status == status)
    if tag: stmt = stmt.where(Experiment.tags_json.contains(f'"{tag}"'))
    column = getattr(Experiment, sort)
    stmt = stmt.order_by(column.desc() if order == "desc" else column.asc()).offset(offset).limit(limit)
    rows = db.scalars(stmt).all()
    if q:
        term = f"%{q}%"; count_stmt = count_stmt.where(or_(Experiment.name.ilike(term), Experiment.description.ilike(term)))
    if category: count_stmt = count_stmt.where(Experiment.category == category)
    if simulation: count_stmt = count_stmt.where(Experiment.simulation == simulation)
    if status: count_stmt = count_stmt.where(Experiment.status == status)
    if tag: count_stmt = count_stmt.where(Experiment.tags_json.contains(f'"{tag}"'))
    total = db.scalar(count_stmt) or 0
    return {"items": [experiment_dict(r, False) for r in rows], "total": int(total), "limit": limit, "offset": offset}


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: str, db: Session = Depends(get_db)):
    return experiment_dict(_get(db, experiment_id))


@router.patch("/experiments/{experiment_id}")
def update_experiment(experiment_id: str, req: ExperimentPatch, db: Session = Depends(get_db)):
    row = _get(db, experiment_id)
    changes = req.model_dump(exclude_unset=True)
    configuration_changed = any(changes.get(key) is not None for key in ("config", "simulation"))
    for key, value in changes.items():
        if value is not None:
            setattr(row, "tags_json" if key == "tags" else "config_json" if key == "config" else key,
                    dumps(value) if key in ("tags", "config") else value)
    if configuration_changed:
        row.result_json = None
        row.status = "draft"
    row.updated_at = now(); row.version += 1
    db.commit(); db.refresh(row)
    record_event(db, "Research", f"Experiment {row.name} updated", experiment_id=row.id)
    return experiment_dict(row)


@router.delete("/experiments/{experiment_id}")
def delete_experiment(experiment_id: str, db: Session = Depends(get_db)):
    row = _get(db, experiment_id)
    name = row.name
    executions = db.scalars(select(ExperimentExecution).where(ExperimentExecution.experiment_id == row.id)).all()
    for execution in executions:
        delete_result_artifact(execution.result_json)
        db.delete(execution)
    # The latest experiment result may share an artifact with its most recent execution.
    if row.result_json and not any(e.result_json == row.result_json for e in executions):
        delete_result_artifact(row.result_json)
    db.delete(row); db.commit()
    record_event(db, "Research", f"Experiment {name} deleted")
    return {"deleted": True, "id": experiment_id}


@router.post("/experiments/{experiment_id}/duplicate")
def duplicate_experiment(experiment_id: str, db: Session = Depends(get_db)):
    src = _get(db, experiment_id); ts = now()
    row = Experiment(id=str(uuid.uuid4()), name=f"{src.name} (copy)", description=src.description, category=src.category,
                     simulation=src.simulation, created_at=ts, updated_at=ts, status="draft",
                     config_json=src.config_json, notes=src.notes, tags_json=src.tags_json, version=1, owner_id=db.info.get("user_id"))
    db.add(row); db.commit(); db.refresh(row)
    record_event(db, "Research", f"Experiment {row.name} duplicated", experiment_id=row.id)
    return experiment_dict(row)


@router.post("/experiments/{experiment_id}/run")
def run_experiment(experiment_id: str, db: Session = Depends(get_db)):
    row = _get(db, experiment_id)
    execution = execute_and_persist(db, row)
    if execution.status == "failed":
        raise HTTPException(422, detail={"code": "execution_failed", "message": "Experiment execution failed", "errors": [execution.error]})
    return {"experiment": experiment_dict(row), "execution": execution_dict(execution)}


@router.get("/experiments/{experiment_id}/executions")
def executions(experiment_id: str, db: Session = Depends(get_db)):
    _get(db, experiment_id)
    rows = db.scalars(select(ExperimentExecution).where(ExperimentExecution.experiment_id == experiment_id).order_by(ExperimentExecution.created_at.desc())).all()
    return [execution_dict(r, False) for r in rows]


@router.get("/executions/{execution_id}")
def get_execution(execution_id: str, db: Session = Depends(get_db)):
    row = db.get(ExperimentExecution, execution_id)
    if row is not None and db.info.get("user_id"):
        parent = db.get(Experiment, row.experiment_id)
        if parent is None or (db.info.get("user_role") != "admin" and parent.owner_id != db.info.get("user_id")): row = None
    if row is None: raise HTTPException(404, detail={"code": "not_found", "message": "Execution not found", "errors": []})
    return execution_dict(row)


@router.post("/executions/{execution_id}/replay")
def replay_execution(execution_id: str, db: Session = Depends(get_db)):
    original = db.get(ExperimentExecution, execution_id)
    if original is not None and db.info.get("user_id"):
        parent = db.get(Experiment, original.experiment_id)
        if parent is None or (db.info.get("user_role") != "admin" and parent.owner_id != db.info.get("user_id")): original = None
    if original is None: raise HTTPException(404, detail={"code": "not_found", "message": "Execution not found", "errors": []})
    experiment = _get(db, original.experiment_id)
    # Replay runs the immutable execution snapshot, never mutating the original execution.
    replay_exp = Experiment(id=str(uuid.uuid4()), name=f"Replay: {experiment.name}", description="Replay generated from an immutable execution snapshot",
        category=experiment.category, simulation=experiment.simulation, created_at=now(), updated_at=now(), status="draft",
        config_json=original.config_json, notes="", tags_json="[]", version=1, owner_id=db.info.get("user_id"))
    db.add(replay_exp); db.commit()
    result = execute_and_persist(db, replay_exp, replay_of=original.id)
    if result.status == "failed": raise HTTPException(422, detail={"code":"replay_failed","message":"Replay failed","errors":[result.error]})
    original_result = load_result(original.result_json)
    replay_result = load_result(result.result_json)
    original_metrics = flatten_metrics(original_result) if isinstance(original_result, dict) else {}
    replay_metrics = flatten_metrics(replay_result) if isinstance(replay_result, dict) else {}
    common = sorted(k for k in set(original_metrics) & set(replay_metrics)
                    if isinstance(original_metrics[k], (int, float)) and not isinstance(original_metrics[k], bool)
                    and isinstance(replay_metrics[k], (int, float)) and not isinstance(replay_metrics[k], bool))
    deterministic = original_result.get("deterministic") if isinstance(original_result, dict) else None
    comparison = {"same_result": original_result == replay_result, "deterministic": deterministic,
                  "metrics": [{"key":k,"original":original_metrics[k],"replay":replay_metrics[k],
                               "delta":replay_metrics[k]-original_metrics[k]} for k in common[:100]],
                  "note": ("The engine marks this result deterministic; exact result equality is expected for an identical software version and configuration." if deterministic is True
                           else "The engine does not provide an explicit deterministic flag. Equality is an observed comparison, not a reproducibility guarantee." if deterministic is None
                           else "The engine marks this result nondeterministic; replay values may legitimately differ.")}
    return {"original": execution_dict(original, False), "replay_experiment": experiment_dict(replay_exp),
            "execution": execution_dict(result), "comparison": comparison}


@router.post("/compare")
def compare_experiments(ids: list[str] = Body(min_length=2, max_length=8), db: Session = Depends(get_db)):
    if len(set(ids)) != len(ids):
        raise HTTPException(422, detail={"code":"duplicate_experiments","message":"Select each experiment only once","errors":[]})
    rows = [_get(db, x) for x in ids]
    simulations = {r.simulation for r in rows}
    if len(simulations) != 1:
        raise HTTPException(409, detail={"code":"incompatible_simulations","message":"Compare experiments from the same simulation family so metric definitions remain meaningful","errors":[]})
    snapshots = [(r, load_result(r.result_json)) for r in rows]
    if any(r.status != "completed" or not result for (r, result) in snapshots):
        raise HTTPException(409, detail={"code":"missing_results","message":"Every selected experiment must have a completed result","errors":[]})
    flattened = [(r, flatten_metrics(result)) for r, result in snapshots]
    common = set.intersection(*(set(m.keys()) for _, m in flattened))
    numeric = sorted(k for k in common if all(isinstance(m[k], (int, float)) and not isinstance(m[k], bool) for _, m in flattened))
    return {"experiments":[{"id":r.id,"name":r.name,"simulation":r.simulation,"config":loads(r.config_json)} for r,_ in flattened],
            "compatible_metrics":numeric,
            "metrics":[{"key":k,"values":[{"experiment_id":r.id,"name":r.name,"value":m[k]} for r,m in flattened]} for k in numeric],
            "note":"Only identically named numeric result fields are compared. Matching field names do not guarantee equivalent methodology; inspect configurations and simulation versions."}


@router.get("/activity")
def activity(limit: int = Query(100, ge=1, le=500), category: str | None = None, db: Session = Depends(get_db)):
    stmt = select(ActivityEvent).order_by(ActivityEvent.id.desc()).limit(limit)
    if db.info.get("user_id") and db.info.get("user_role") != "admin":
        owned_ids = select(Experiment.id).where(Experiment.owner_id == db.info["user_id"])
        stmt = select(ActivityEvent).where(ActivityEvent.experiment_id.in_(owned_ids)).order_by(ActivityEvent.id.desc()).limit(limit)
    if category:
        stmt = stmt.where(ActivityEvent.category == category)
    rows = db.scalars(stmt).all()
    events = [{"id":r.id,"created_at":r.created_at,"category":r.category,"severity":r.severity,
        "message":r.message,"experiment_id":r.experiment_id,"data":loads(r.data_json),"source":"persistent"} for r in rows]
    # Direct lab routes still publish session-scoped events. Include them without duplicating
    # workbench events, which already have durable ActivityEvent rows.
    for event in ([] if db.info.get("user_id") else bus.recent(200)):
        if event["data"].get("experiment_id"):
            continue
        if category and event["category"] != category:
            continue
        events.append({"id":f"session-{event['id']}","created_at":event["ts"],"category":event["category"],
                       "severity":event["severity"],"message":event["message"],"experiment_id":None,
                       "data":event["data"],"source":"session"})
    events.sort(key=lambda e: e["created_at"], reverse=True)
    return {"events":events[:limit]}


@router.get("/operations")
def operations(db: Session = Depends(get_db)):
    owned_ids = select(Experiment.id).where(Experiment.owner_id == db.info["user_id"]) if db.info.get("user_id") and db.info.get("user_role") != "admin" else None
    active_stmt = select(ExperimentExecution).where(ExperimentExecution.status == "running")
    recent_stmt = select(ExperimentExecution)
    if owned_ids is not None:
        active_stmt = active_stmt.where(ExperimentExecution.experiment_id.in_(owned_ids))
        recent_stmt = recent_stmt.where(ExperimentExecution.experiment_id.in_(owned_ids))
    active = db.scalars(active_stmt.order_by(ExperimentExecution.created_at.desc())).all()
    recent = db.scalars(recent_stmt.order_by(ExperimentExecution.created_at.desc()).limit(12)).all()
    execution_ids = {r.experiment_id for r in [*active, *recent]}
    experiment_rows = db.scalars(select(Experiment).where(Experiment.id.in_(execution_ids))).all() if execution_ids else []
    experiments = {r.id:r for r in experiment_rows}
    def describe(row):
        payload = execution_dict(row, False)
        experiment = experiments.get(row.experiment_id)
        payload["experiment_name"] = experiment.name if experiment else "Deleted experiment"
        payload["simulation"] = experiment.simulation if experiment else "unknown"
        return payload
    counts = {s: int(db.scalar(select(func.count()).select_from(ExperimentExecution).where(ExperimentExecution.status == s, *([ExperimentExecution.experiment_id.in_(owned_ids)] if owned_ids is not None else []))) or 0) for s in ("completed","failed","running")}
    return {"active": [describe(r) for r in active], "recent": [describe(r) for r in recent], "counts": counts,
            "connection": "polling", "note": "Simulation engines execute synchronously in the current API process; running jobs may only be observable during the request."}
