from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.events import bus
from app.simulation.cpu.instruction import AssemblyError
from app.simulation.cpu.processor import SimulationInputError, simulate
from app.simulation.cpu.workloads import SAMPLE_WORKLOADS

router = APIRouter(prefix="/architecture", tags=["architecture"])


class ArchitectureRequest(BaseModel):
    program: str = Field(min_length=1, max_length=20000)
    num_registers: int = 8
    forwarding: bool = True
    max_cycles: int = Field(2000, ge=10, le=5000)
    memory_size_words: int = Field(256, ge=16, le=4096)
    clock_mhz: float = Field(100.0, gt=0, le=10000)
    initial_registers: dict[int, int] = Field(default_factory=dict)
    initial_memory: dict[int, int] = Field(default_factory=dict)


@router.post("/simulate")
def run_simulation(req: ArchitectureRequest) -> dict:
    try:
        result = simulate(**req.model_dump())
    except (AssemblyError, SimulationInputError) as e:
        code = "assembly_error" if isinstance(e, AssemblyError) else "invalid_config"
        raise HTTPException(status_code=422, detail={"code": code, "message": "Simulation input rejected", "errors": e.errors}) from e
    m = result["metrics"]
    bus.publish("CPU", f"Pipeline simulation {result['status']}: {m['cycles']} cycles, {m['instructions_retired']} instructions retired",
                "warning" if result["status"] in ("max_cycles", "fault") else "info",
                {"experiment": True, "status": result["status"], "cycles": m["cycles"], "cpi": m["cpi"], "forwarding": req.forwarding})
    return result


@router.get("/workloads")
def workloads() -> dict:
    return SAMPLE_WORKLOADS
