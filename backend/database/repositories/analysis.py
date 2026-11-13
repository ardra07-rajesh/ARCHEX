import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import AnalysisRecord


def save(db: Session, result: dict) -> int:
    row = AnalysisRecord(created_at=result["created_at"], scenario=result["trace"]["generated_scenario"], seed=result["trace"]["seed"],
                         classification=result["detection"]["classification"], anomaly_score=result["detection"]["anomaly_score"],
                         result_json=json.dumps(result), owner_id=db.info.get("user_id"))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def list_recent(db: Session, limit: int = 50) -> list[dict]:
    stmt = select(AnalysisRecord).order_by(AnalysisRecord.id.desc()).limit(limit)
    if db.info.get("user_id") and db.info.get("user_role") != "admin": stmt = select(AnalysisRecord).where(AnalysisRecord.owner_id == db.info["user_id"]).order_by(AnalysisRecord.id.desc()).limit(limit)
    rows = db.scalars(stmt).all()
    return [{"id": r.id, "created_at": r.created_at, "scenario": r.scenario, "seed": r.seed, "classification": r.classification,
             "anomaly_score": r.anomaly_score} for r in rows]


def get(db: Session, record_id: int) -> dict | None:
    r = db.get(AnalysisRecord, record_id)
    if r is not None and db.info.get("user_id") and db.info.get("user_role") != "admin" and r.owner_id != db.info.get("user_id"): r = None
    return None if r is None else {"record_id": r.id, **json.loads(r.result_json)}


def counts(db: Session) -> tuple[int, int]:
    base = select(AnalysisRecord)
    if db.info.get("user_id") and db.info.get("user_role") != "admin": base = base.where(AnalysisRecord.owner_id == db.info["user_id"])
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    anomalous = db.scalar(select(func.count()).select_from(AnalysisRecord).where(AnalysisRecord.classification == "anomalous", *([AnalysisRecord.owner_id == db.info["user_id"]] if db.info.get("user_id") and db.info.get("user_role") != "admin" else []))) or 0
    return int(total), int(anomalous)
