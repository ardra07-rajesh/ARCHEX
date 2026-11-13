from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.events import bus
from app.simulation.timing.timing_engine import TimingInputError, run_timing_experiment

router = APIRouter(prefix="/side-channel", tags=["side-channel"])


class Defence(BaseModel):
    timing_noise_std: float = Field(0.0, ge=0, le=1000)
    constant_time: bool = False
    flush_probability: float = Field(0.0, ge=0, le=1)


class SideChannelRequest(BaseModel):
    samples: int = Field(2000, ge=50, le=20000)
    seed: int = Field(0, ge=0, le=2**31 - 1)
    hit_latency_mean: float = Field(40.0, ge=1, le=10000)
    miss_latency_mean: float = Field(200.0, ge=2, le=10000)
    jitter_std: float = Field(15.0, ge=0, le=1000)
    defence: Defence | None = None


@router.post("/simulate")
def simulate(req: SideChannelRequest) -> dict:
    try:
        result = run_timing_experiment(req.model_dump())
    except TimingInputError as e:
        raise HTTPException(422, detail={"code": "invalid_input", "message": "Experiment input rejected", "errors": e.errors}) from e
    b = result["baseline"]
    bus.publish("Timing", f"Timing experiment: baseline distinguishability {b['distinguishability']:.3f} ({b['leakage_indicator']} leakage indicator)",
                data={"experiment": True, "distinguishability": b["distinguishability"], "samples": req.samples})
    return result
