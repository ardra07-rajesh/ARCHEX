from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.events import bus
from app.simulation.cache.cache_engine import CacheConfigError, compare_caches, simulate_cache
from app.simulation.cache.workloads import MAX_ACCESSES, PATTERNS

router = APIRouter(prefix="/cache", tags=["cache"])


class LevelCfg(BaseModel):
    name: str | None = Field(None, max_length=8)
    size_bytes: int = Field(ge=4, le=1 << 24)
    block_size: int = Field(32, ge=4, le=256)
    mapping: Literal["direct", "set_associative", "fully_associative"] = "set_associative"
    associativity: int = Field(4, ge=1, le=4096)
    policy: Literal["FIFO", "LRU", "Random"] = "LRU"
    hit_latency: int = Field(1, ge=1, le=1000)


class WorkloadCfg(BaseModel):
    pattern: Literal["sequential", "strided", "random", "hot_cold", "matrix_row", "matrix_col", "explicit"] = "sequential"
    count: int = Field(2000, ge=1, le=MAX_ACCESSES)
    stride: int = Field(4, ge=1, le=1 << 16)
    working_set_bytes: int = Field(8192, ge=4, le=1 << 24)
    matrix_dim: int = Field(32, ge=2, le=128)
    addresses: list[int] = Field(default_factory=list, max_length=MAX_ACCESSES)


class CacheRequest(BaseModel):
    levels: list[LevelCfg] = Field(min_length=1, max_length=3)
    memory_latency: int = Field(100, ge=1, le=10000)
    workload: WorkloadCfg = WorkloadCfg()
    seed: int = Field(0, ge=0, le=2**31 - 1)


class NamedConfig(BaseModel):
    label: str = Field(max_length=60)
    levels: list[LevelCfg] = Field(min_length=1, max_length=3)
    memory_latency: int = Field(100, ge=1, le=10000)


class CompareRequest(BaseModel):
    configs: list[NamedConfig] = Field(min_length=2, max_length=6)
    workload: WorkloadCfg = WorkloadCfg()
    seed: int = Field(0, ge=0, le=2**31 - 1)


def _reject(e: CacheConfigError):
    raise HTTPException(422, detail={"code": "invalid_cache_config", "message": "Cache configuration rejected", "errors": e.errors}) from e


@router.post("/simulate")
def run(req: CacheRequest) -> dict:
    try:
        result = simulate_cache([l.model_dump() for l in req.levels], req.memory_latency, req.workload.model_dump(), req.seed)
    except CacheConfigError as e:
        _reject(e)
    s = result["summary"]
    bus.publish("Cache", f"Cache simulation ({req.workload.pattern}): hierarchy hit ratio {s['hierarchy_hit_ratio']:.1%} over {s['accesses']} accesses",
                data={"experiment": True, "pattern": req.workload.pattern, "hierarchy_hit_ratio": s["hierarchy_hit_ratio"], "accesses": s["accesses"]})
    return result


@router.post("/compare")
def compare(req: CompareRequest) -> dict:
    try:
        return compare_caches([{"label": c.label, "memory_latency": c.memory_latency, "levels": [l.model_dump() for l in c.levels]} for c in req.configs],
                              req.workload.model_dump(), req.seed)
    except CacheConfigError as e:
        _reject(e)


@router.get("/defaults")
def defaults() -> dict:
    return {
        "levels": [
            {"name": "L1", "size_bytes": 1024, "block_size": 32, "mapping": "set_associative", "associativity": 2, "policy": "LRU", "hit_latency": 1},
            {"name": "L2", "size_bytes": 8192, "block_size": 32, "mapping": "set_associative", "associativity": 4, "policy": "LRU", "hit_latency": 10},
            {"name": "L3", "size_bytes": 65536, "block_size": 64, "mapping": "set_associative", "associativity": 8, "policy": "LRU", "hit_latency": 30},
        ],
        "memory_latency": 100,
        "patterns": PATTERNS,
    }
