from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import VERSION, settings
from app.database.session import check_database
from app.ai.pipeline import model_status
from app.simulation.cpu.processor import self_test

router = APIRouter(tags=["health"])
Status = Literal["online", "offline", "unavailable"]


class Component(BaseModel):
    status: Status
    detail: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    timestamp: str
    components: dict[str, Component]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    db_ok, db_detail = check_database()
    engine_ok = self_test()
    ai_status, ai_detail = model_status()
    components = {
        "api": Component(status="online", detail="FastAPI responding"),
        "database": Component(
            status="online" if db_ok else "offline",
            detail=f"{db_detail} connection OK" if db_ok else f"Connection failed: {db_detail}",
        ),
        # Component health reflects the local assistant service, even without an external LLM.
        "simulation_engine": Component(
            status="online" if engine_ok else "offline",
            detail="CPU simulator self-test passed" if engine_ok else "CPU simulator self-test FAILED",
        ),
        "ai_service": Component(status=ai_status, detail=ai_detail),
        "assistant": Component(
            status="online",
            detail=(f"{settings.llm_provider} provider configured ({settings.llm_model})" if settings.llm_provider and settings.llm_api_key
                    else "Local deterministic fallback available; no external LLM provider configured"),
        ),
    }
    degraded = components["database"].status != "online" or not engine_ok
    return HealthResponse(
        status="degraded" if degraded else "ok",
        version=VERSION,
        environment=settings.env,
        timestamp=datetime.now(timezone.utc).isoformat(),
        components=components,
    )
