from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.events import bus
from app.simulation.cache.cache_engine import CacheConfigError
from app.simulation.defence.comparison import DefenceInputError, compare_defences
from app.simulation.defence.countermeasures import DEFENCES

router = APIRouter(prefix="/defence", tags=["defence"])


class DefenceCfg(BaseModel):
    cache_partitioning: bool = False
    memory_isolation: bool = False
    cache_flushing: bool = False
    constant_time: bool = False
    speculation_restriction: bool = False
    timing_noise_std: float = Field(0.0, ge=0, le=5000)


class DefenceRequest(BaseModel):
    defences: DefenceCfg = DefenceCfg()
    rounds: int = Field(150, ge=40, le=600)
    perf_accesses: int = Field(4000, ge=500, le=20000)
    seed: int = Field(0, ge=0, le=2**31 - 1)
    jitter_std: float = Field(30.0, ge=0, le=1000)
    p_spec: float = Field(0.5, ge=0, le=1)
    spec_lines: int = Field(4, ge=1, le=8)
    include_singles: bool = True
    include_recommendations: bool = True


@router.post("/compare")
def compare(req: DefenceRequest) -> dict:
    p = req.model_dump(exclude={"defences", "include_singles", "include_recommendations"})
    try:
        result = compare_defences(req.defences.model_dump(), p, req.include_singles, req.include_recommendations)
    except (DefenceInputError, CacheConfigError) as e:
        raise HTTPException(422, detail={"code": "invalid_input", "message": "Defence experiment rejected", "errors": e.errors}) from e
    c = result["comparison"]
    bus.publish("Defence", f"Defence comparison: distinguishability {c['distinguishability_baseline']:.3f} -> {c['distinguishability_protected']:.3f}, overhead {c['overhead_pct']:.1f}%",
                data={"experiment": True, "distinguishability_protected": c["distinguishability_protected"]})
    return result


@router.get("/catalog")
def catalog() -> dict:
    return DEFENCES
