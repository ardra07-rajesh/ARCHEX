from .instruction import assemble
from .pipeline import Memory, MemoryFault, Pipeline
from .registers import RegisterFile

ALLOWED_REGISTER_COUNTS = (8, 16, 32)


class SimulationInputError(ValueError):
    def __init__(self, errors: list[dict]):
        super().__init__("; ".join(e["message"] for e in errors))
        self.errors = errors


def simulate(program: str, *, num_registers: int = 8, forwarding: bool = True, max_cycles: int = 2000,
             memory_size_words: int = 256, clock_mhz: float = 100.0,
             initial_registers: dict[int, int] | None = None, initial_memory: dict[int, int] | None = None) -> dict:
    if num_registers not in ALLOWED_REGISTER_COUNTS:
        raise SimulationInputError([{"line": 0, "message": f"num_registers must be one of {ALLOWED_REGISTER_COUNTS}"}])
    prog = assemble(program, num_registers)  # raises AssemblyError (has .errors)

    regs = RegisterFile(num_registers)
    for r, v in (initial_registers or {}).items():
        if not 1 <= r < num_registers:
            raise SimulationInputError([{"line": 0, "message": f"initial register R{r} invalid (R1..R{num_registers - 1}; R0 is fixed at zero)"}])
        regs.write(r, v)
    try:
        mem = Memory(memory_size_words, initial_memory)
    except MemoryFault as e:
        raise SimulationInputError([{"line": 0, "message": f"initial memory: {e}"}]) from e

    pipe = Pipeline(prog, regs, mem, forwarding)
    cycles: list[dict] = []
    status = "max_cycles"
    while len(cycles) < max_cycles:
        if pipe.empty() and pipe.pc >= len(prog):
            status = "end_of_program"
            break
        cycles.append(pipe.step())
        if pipe.halted:
            status = "halted"
            break
        if pipe.fault:
            status = "fault"
            break

    n = len(cycles)
    return {
        "data_source": "simulated",
        "deterministic": True,
        "status": status,
        "fault": pipe.fault,
        "config": {"num_registers": num_registers, "forwarding": forwarding, "max_cycles": max_cycles,
                   "memory_size_words": memory_size_words, "clock_mhz": clock_mhz},
        "instructions": [{"index": i, "text": ins.text, "line": ins.line} for i, ins in enumerate(prog)],
        "metrics": {
            "cycles": n,
            "instructions_retired": pipe.retired,
            "cpi": round(n / pipe.retired, 4) if pipe.retired else None,
            "ideal_cycles": pipe.retired + 4 if pipe.retired else 0,
            "stall_cycles": pipe.stalls,
            "flush_events": pipe.flushes,
            "flushed_instructions": pipe.flushed_instrs,
            "forwarding_events": pipe.forwards,
            "branches": pipe.branches,
            "branches_taken": pipe.taken,
            "execution_time_us": round(n / clock_mhz, 4),
        },
        "cycles": cycles,
        "final_registers": regs.snapshot(),
        "final_memory": {str(a): v for a, v in sorted(mem.data.items()) if v != 0},
    }


def self_test() -> bool:
    """Real engine probe used by /health."""
    try:
        r = simulate("ADDI R1, R0, 7\nADD R2, R1, R1\nHALT")
        return r["status"] == "halted" and r["final_registers"][2] == 14
    except Exception:  # noqa: BLE001
        return False
