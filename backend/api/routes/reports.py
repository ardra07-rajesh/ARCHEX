"""Report generation and lifecycle endpoints."""
import uuid
import json
import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database.models import Experiment, ExperimentExecution, ResearchReport
from app.database.session import get_db
from app.services.research import now, record_event
from app.services.reports import (ALLOWED_SECTIONS, build_payload, create_file, safe_report_path)

router = APIRouter(prefix="/reports", tags=["reports"])


class ReportRequest(BaseModel):
    experiment_id: str = Field(min_length=1, max_length=36)
    format: Literal["pdf", "csv", "json"]
    title: str | None = Field(None, max_length=200)
    sections: list[str] = Field(default_factory=lambda: ["executive_summary", "background", "methodology", "configuration", "results", "discussion", "conclusion"], max_length=7)
    detail_level: Literal["concise", "technical"] = "technical"

    @field_validator("sections")
    @classmethod
    def valid_sections(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(item not in ALLOWED_SECTIONS for item in value):
            raise ValueError("Report sections contain duplicates or unsupported values")
        return value


def _report_dict(row: ResearchReport) -> dict:
    return {"id": row.id, "experiment_id": row.experiment_id, "title": row.title,
            "format": row.report_type, "status": row.status, "created_at": row.created_at,
            "file_size": row.file_size, "sections": __import__("json").loads(row.sections_json or "[]"),
            "detail_level": row.detail_level, "experiment_version": row.experiment_version}


@router.post("/generate")
def generate_report(req: ReportRequest, db: Session = Depends(get_db)):
    experiment = db.get(Experiment, req.experiment_id)
    if experiment is not None and db.info.get("user_id") and db.info.get("user_role") != "admin" and experiment.owner_id != db.info.get("user_id"): experiment = None
    if experiment is None:
        raise HTTPException(404, detail={"code":"experiment_not_found","message":"Experiment not found","errors":[]})
    executions = db.scalars(select(ExperimentExecution).where(ExperimentExecution.experiment_id == experiment.id)
                            .order_by(ExperimentExecution.created_at.asc())).all()
    report_id = str(uuid.uuid4())
    title = (req.title or f"{experiment.name} — Research Report").strip()
    if not title:
        raise HTTPException(422, detail={"code":"invalid_title","message":"Report title cannot be empty","errors":[]})
    payload = build_payload(experiment, executions, title, req.sections, req.detail_level)
    payload["report_id"] = report_id
    payload["generated_at"] = now()
    try:
        filename, content = create_file(req.format, payload)
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, detail={"code":"report_generation_failed","message":"The report could not be generated","errors":[type(exc).__name__]}) from exc
    row = ResearchReport(id=report_id, experiment_id=experiment.id, title=title, report_type=req.format,
                         status="completed", created_at=payload["generated_at"], filename=filename,
                         file_size=len(content), sections_json=__import__("json").dumps(req.sections),
                         detail_level=req.detail_level, experiment_version=experiment.version, owner_id=db.info.get("user_id"))
    db.add(row); db.commit(); db.refresh(row)
    record_event(db, "Reports", f"{req.format.upper()} report generated for {experiment.name}",
                 experiment_id=experiment.id, data={"report_id":report_id,"format":req.format})
    return _report_dict(row)


@router.get("")
def list_reports(experiment_id: str | None = None, format: Literal["pdf", "csv", "json"] | None = None,
                 limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                 db: Session = Depends(get_db)):
    stmt = select(ResearchReport)
    count = select(func.count()).select_from(ResearchReport)
    if db.info.get("user_id") and db.info.get("user_role") != "admin":
        stmt = stmt.where(ResearchReport.owner_id == db.info["user_id"])
        count = count.where(ResearchReport.owner_id == db.info["user_id"])
    if experiment_id:
        stmt = stmt.where(ResearchReport.experiment_id == experiment_id); count = count.where(ResearchReport.experiment_id == experiment_id)
    if format:
        stmt = stmt.where(ResearchReport.report_type == format); count = count.where(ResearchReport.report_type == format)
    rows = db.scalars(stmt.order_by(ResearchReport.created_at.desc()).offset(offset).limit(limit)).all()
    return {"items":[_report_dict(r) for r in rows], "total":int(db.scalar(count) or 0), "limit":limit, "offset":offset}


@router.get("/{report_id}/preview")
def preview_report(report_id: str, db: Session = Depends(get_db)):
    row = db.get(ResearchReport, report_id)
    if row is not None and db.info.get("user_id") and db.info.get("user_role") != "admin" and row.owner_id != db.info.get("user_id"): row = None
    if row is None: raise HTTPException(404, detail={"code":"report_not_found","message":"Report not found","errors":[]})
    try: path = safe_report_path(row.filename)
    except ValueError as exc: raise HTTPException(400, detail={"code":"invalid_report_path","message":"Invalid report file","errors":[]}) from exc
    if not path.is_file(): raise HTTPException(410, detail={"code":"report_file_missing","message":"Report file is no longer available","errors":[]})
    if row.report_type == "pdf":
        return {"format":"pdf", "preview_mode":"inline_document", "title":row.title}
    raw = path.read_text(encoding="utf-8-sig")
    if row.report_type == "json":
        try: data = json.loads(raw)
        except ValueError: raise HTTPException(500, detail={"code":"report_corrupt","message":"Report content is invalid","errors":[]})
        preview = json.dumps(data, ensure_ascii=False, indent=2)
        return {"format":"json", "content":preview[:65000], "truncated":len(preview)>65000}
    lines = raw.splitlines()[:51]
    return {"format":"csv", "content":"\n".join(lines), "truncated":len(raw.splitlines())>51}


@router.get("/{report_id}")
def get_report(report_id: str, db: Session = Depends(get_db)):
    row = db.get(ResearchReport, report_id)
    if row is not None and db.info.get("user_id") and db.info.get("user_role") != "admin" and row.owner_id != db.info.get("user_id"): row = None
    if row is None: raise HTTPException(404, detail={"code":"report_not_found","message":"Report not found","errors":[]})
    return _report_dict(row)


@router.get("/{report_id}/download")
def download_report(report_id: str, disposition: Literal["attachment", "inline"] = Query("attachment"), db: Session = Depends(get_db)):
    row = db.get(ResearchReport, report_id)
    if row is not None and db.info.get("user_id") and db.info.get("user_role") != "admin" and row.owner_id != db.info.get("user_id"): row = None
    if row is None: raise HTTPException(404, detail={"code":"report_not_found","message":"Report not found","errors":[]})
    try: path = safe_report_path(row.filename)
    except ValueError as exc: raise HTTPException(400, detail={"code":"invalid_report_path","message":"Invalid report file","errors":[]}) from exc
    if not path.is_file(): raise HTTPException(410, detail={"code":"report_file_missing","message":"Report file is no longer available","errors":[]})
    media = {"pdf":"application/pdf", "csv":"text/csv; charset=utf-8", "json":"application/json"}[row.report_type]
    return FileResponse(path, media_type=media, filename=f"{row.title[:100]}.{row.report_type}", content_disposition_type=disposition)


@router.delete("/{report_id}")
def delete_report(report_id: str, db: Session = Depends(get_db)):
    row = db.get(ResearchReport, report_id)
    if row is not None and db.info.get("user_id") and db.info.get("user_role") != "admin" and row.owner_id != db.info.get("user_id"): row = None
    if row is None: raise HTTPException(404, detail={"code":"report_not_found","message":"Report not found","errors":[]})
    try: safe_report_path(row.filename).unlink(missing_ok=True)
    except ValueError: pass
    experiment_id = row.experiment_id
    db.delete(row); db.commit()
    record_event(db, "Reports", f"Research report {report_id} deleted", experiment_id=experiment_id,
                 data={"report_id":report_id})
    return {"deleted":True,"id":report_id}
