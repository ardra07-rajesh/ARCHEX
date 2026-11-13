from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.events import bus
from app.simulation.branch.predictors import KINDS, run_predictor
from app.simulation.branch.speculation import run_speculation
from app.simulation.branch.workloads import KINDS as WORKLOAD_KINDS, BranchInputError, generate_branches
from app.simulation.cache.cache_engine import CacheConfigError

router = APIRouter(prefix="/speculation", tags=["speculation"])


class BranchWorkload(BaseModel):
    kind: Literal["loop", "nested_loops", "alternating", "biased_random", "explicit"] = "loop"
    loop_iterations: int = Field(10, ge=1, le=1000)
    repeats: int = Field(5, ge=1, le=1000)
    outer: int = Field(5, ge=1, le=200)
    inner: int = Field(4, ge=1, le=200)
    count: int = Field(40, ge=1, le=5000)
    p_taken: float = Field(0.7, ge=0, le=1)
    outcomes: str = Field("", max_length=5000)


class SpeculationCfg(BaseModel):
    window: int = Field(8, ge=1, le=64)
    spec_loads: int = Field(2, ge=1, le=16)
    loads_per_branch: int = Field(1, ge=1, le=8)
    working_set_bytes: int = Field(256, ge=32, le=65536)
    cache_size_bytes: int = Field(256, ge=64, le=65536)
    block_size: int = Field(32, ge=8, le=128)
    associativity: int = Field(8, ge=1, le=64)


class SpeculationRequest(BaseModel):
    predictor: Literal["always_taken", "always_not_taken", "one_bit", "two_bit"] = "two_bit"
    workload: BranchWorkload = BranchWorkload()
    table_size: int = Field(16, ge=1, le=1024)
    initial_state: int | None = Field(None, ge=0, le=3)
    mispredict_penalty: int = Field(2, ge=0, le=50)
    speculation: SpeculationCfg | None = None
    seed: int = Field(0, ge=0, le=2**31 - 1)


@router.post("/simulate")
def simulate(req: SpeculationRequest) -> dict:
    try:
        seq = generate_branches(req.workload.model_dump(), req.seed)
        run = run_predictor(req.predictor, seq, req.table_size, req.initial_state, req.mispredict_penalty)
        comparison = [{"predictor": k, **run_predictor(k, seq, req.table_size, req.initial_state if k == req.predictor else None, req.mispredict_penalty)["metrics"]} for k in KINDS]
        spec = run_speculation(run["steps"], req.speculation.model_dump(), req.seed) if req.speculation else None
    except (BranchInputError, CacheConfigError) as e:
        raise HTTPException(422, detail={"code": "invalid_input", "message": "Simulation input rejected", "errors": e.errors}) from e
    m = run["metrics"]
    bus.publish("Branch", f"Branch simulation ({req.predictor}, {req.workload.kind}): accuracy {m['accuracy']:.1%} over {m['branches']} branches",
                data={"experiment": True, "predictor": req.predictor, "accuracy": m["accuracy"], "branches": m["branches"]})
    return {"data_source": "simulated", "deterministic": True, "config": req.model_dump(), "run": run, "comparison": comparison, "speculation": spec}


@router.get("/workloads")
def workloads() -> dict:
    return WORKLOAD_KINDS
