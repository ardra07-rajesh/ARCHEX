"""Advanced, synthetic microarchitecture research endpoints."""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.events import bus
from app.simulation.advanced.engine import multi_seed_branch_evaluation, run_advanced_predictor, run_contention
from app.simulation.branch.workloads import BranchInputError, generate_branches
from app.simulation.cache.cache_engine import CacheConfigError

router = APIRouter(prefix="/advanced", tags=["advanced-microarchitecture"])


class BranchWorkload(BaseModel):
    kind: Literal["loop", "nested_loops", "alternating", "biased_random", "explicit"] = "nested_loops"
    loop_iterations: int = Field(10, ge=1, le=1000)
    repeats: int = Field(5, ge=1, le=1000)
    outer: int = Field(5, ge=1, le=200)
    inner: int = Field(4, ge=1, le=200)
    count: int = Field(200, ge=1, le=5000)
    p_taken: float = Field(0.7, ge=0, le=1)
    outcomes: str = Field("", max_length=5000)


class BranchRequest(BaseModel):
    predictor: Literal["gshare", "tournament"] = "gshare"
    workload: BranchWorkload = BranchWorkload()
    table_size: int = Field(256, ge=16, le=4096)
    history_bits: int = Field(8, ge=2, le=16)
    seed: int = Field(42, ge=0, le=2**31 - 1)

    @model_validator(mode="after")
    def valid_history(self):
        if self.table_size & (self.table_size - 1) or self.history_bits > min(16, self.table_size.bit_length() - 1):
            raise ValueError("table_size must be a power of two and history_bits <= log2(table_size)")
        return self


class ContentionRequest(BaseModel):
    cores: int = Field(4, ge=2, le=8)
    accesses_per_core: int = Field(1000, ge=32, le=10000)
    pattern: Literal["sequential", "strided", "random", "hot_cold", "matrix_row", "matrix_col"] = "hot_cold"
    working_set_bytes: int = Field(8192, ge=128, le=1 << 20)
    cache_size_bytes: int = Field(4096, ge=256, le=1 << 20)
    block_size: int = Field(64, ge=8, le=256)
    associativity: int = Field(4, ge=1, le=256)
    seed: int = Field(42, ge=0, le=2**31 - 1)


class MultiSeedRequest(BranchRequest):
    seeds: list[int] = Field(min_length=2, max_length=50)

    @field_validator("seeds")
    @classmethod
    def valid_seeds(cls, values: list[int]) -> list[int]:
        if len(set(values)) != len(values) or any(v < 0 or v > 2**31 - 1 for v in values):
            raise ValueError("seeds must be unique integers in 0..2147483647")
        return values


def _error(exc: Exception):
    errors = exc.errors if hasattr(exc, "errors") else [{"field": "request", "message": str(exc)}]
    raise HTTPException(422, detail={"code": "invalid_advanced_input", "message": "Advanced simulation input rejected", "errors": errors}) from exc


@router.post("/branch-predictor")
def branch_predictor(req: BranchRequest) -> dict:
    try:
        sequence = generate_branches(req.workload.model_dump(), req.seed)
        result = run_advanced_predictor(req.predictor, sequence, req.table_size, req.history_bits)
    except (ValueError, BranchInputError) as exc:
        _error(exc)
    result.update({"data_source": "simulated", "deterministic": True, "seed": req.seed,
                   "workload": req.workload.model_dump(), "limitations": [
                       "Gshare and tournament predictors use synthetic branch traces.",
                       "No physical branch predictor, pipeline timing, aliasing beyond the configured tables, or hardware counters are measured."]})
    bus.publish("AdvancedBranch", f"{req.predictor} predictor evaluated {result['metrics']['branches']} branches",
                data={"experiment": True, "predictor": req.predictor, "accuracy": result["metrics"]["accuracy"]})
    return result


@router.post("/cache-contention")
def cache_contention(req: ContentionRequest) -> dict:
    try:
        result = run_contention(req.cores, req.accesses_per_core, req.pattern, req.working_set_bytes,
                                req.cache_size_bytes, req.block_size, req.associativity, req.seed)
    except (ValueError, CacheConfigError) as exc:
        _error(exc)
    bus.publish("CacheContention", f"Shared LLC contention simulation across {req.cores} cores",
                data={"experiment": True, "cores": req.cores, "misses": result["summary"]["shared_misses"]})
    return result


@router.post("/multi-seed-evaluation")
def multi_seed_evaluation(req: MultiSeedRequest) -> dict:
    try:
        return multi_seed_branch_evaluation(req.workload.model_dump(), req.predictor, req.seeds,
                                            req.table_size, req.history_bits)
    except (ValueError, BranchInputError) as exc:
        _error(exc)
