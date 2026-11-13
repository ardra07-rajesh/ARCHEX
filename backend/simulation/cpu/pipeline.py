"""Cycle-accurate classic five-stage pipeline (IF, ID, EX, MEM, WB).

Model assumptions (documented in docs/SIMULATION_METHODOLOGY.md):
- Register file writes in the first half of a cycle, reads in the second half (WB->ID needs no stall).
- Optional forwarding EX/MEM->EX and MEM/WB->EX. Load-use still costs one stall cycle.
- Without forwarding, ID stalls until the producer has reached WB.
- Branches resolve in EX with a predict-not-taken policy: a taken branch flushes the 2 younger instructions.
- Memory is single-cycle (cache latency arrives with the Cache Intelligence phase).
- Structural hazards are NOT modelled (separate instruction and data ports are assumed).
"""
from dataclasses import dataclass

from . import alu
from .instruction import BR_OPS, R_OPS, Instruction
from .registers import RegisterFile

STAGES = ("IF", "ID", "EX", "MEM", "WB")


class MemoryFault(Exception):
    pass


class Memory:
    def __init__(self, size_words: int, init: dict[int, int] | None = None):
        self.size = size_words
        self.data: dict[int, int] = {}
        for addr, v in (init or {}).items():
            self.check(addr)
            self.data[addr] = alu.to_signed(v)

    def check(self, addr: int) -> None:
        if addr % 4 or addr < 0 or addr >= self.size * 4:
            raise MemoryFault(f"Invalid address {addr}: must be 4-byte aligned within 0..{self.size * 4 - 4}")

    def read(self, addr: int) -> int:
        self.check(addr)
        return self.data.get(addr, 0)

    def write(self, addr: int, v: int) -> None:
        self.check(addr)
        self.data[addr] = alu.to_signed(v)


@dataclass
class InFlight:
    seq: int
    pc: int
    ins: Instruction
    a: int = 0
    b: int = 0
    alu_result: int = 0
    wb_value: int = 0
    killed: bool = False

    @property
    def label(self) -> str:
        return f"I{self.seq}"


def _info(x: InFlight | None, stalled: bool = False) -> dict | None:
    if x is None:
        return None
    return {"id": x.label, "pc": x.pc, "text": x.ins.text, "killed": x.killed, "stalled": stalled}


class Pipeline:
    def __init__(self, program: list[Instruction], regs: RegisterFile, mem: Memory, forwarding: bool = True):
        self.program, self.regs, self.mem, self.forwarding = program, regs, mem, forwarding
        self.s: dict[str, InFlight | None] = {k: None for k in STAGES}
        self.pc = 0
        self.cycle = 0
        self.seq = 0
        self.fetch_stopped = False
        self.halted = False
        self.fault: str | None = None
        self.retired = self.stalls = self.flushes = self.flushed_instrs = 0
        self.forwards = self.branches = self.taken = 0

    # ---- helpers
    def empty(self) -> bool:
        return all(v is None for v in self.s.values())

    def finished(self) -> bool:
        return self.halted or self.fault is not None or (self.empty() and self.pc >= len(self.program))

    def _fwd(self, reg: int | None, val: int, events: list, who: str) -> int:
        if not reg:
            return val
        m, w = self.s["MEM"], self.s["WB"]
        if m and m.ins.dest() == reg and m.ins.op != "LW":
            self.forwards += 1
            events.append({"type": "forward", "message": f"Forward EX/MEM -> EX: R{reg} = {m.alu_result} ({m.label} to {who})"})
            return m.alu_result
        if w and w.ins.dest() == reg:
            self.forwards += 1
            events.append({"type": "forward", "message": f"Forward MEM/WB -> EX: R{reg} = {w.wb_value} ({w.label} to {who})"})
            return w.wb_value
        return val

    # ---- one clock cycle
    def step(self) -> dict:
        self.cycle += 1
        s = self.s
        if s["IF"] is None and not self.fetch_stopped and self.pc < len(self.program):
            ins = self.program[self.pc]
            self.seq += 1
            s["IF"] = InFlight(self.seq, self.pc, ins)
            self.pc += 1
            if ins.op == "HALT":
                self.fetch_stopped = True

        events: list[dict] = []
        reg_changes: list[dict] = []
        alu_info = None
        mem_access = None

        # WB (register file written before ID reads)
        wb = s["WB"]
        if wb:
            d = wb.ins.dest()
            if d is not None:
                self.regs.write(d, wb.wb_value)
                reg_changes.append({"reg": d, "value": self.regs.read(d)})
                events.append({"type": "reg_write", "message": f"{wb.label} writes R{d} = {wb.wb_value}"})
            self.retired += 1
            if wb.ins.op == "HALT":
                self.halted = True
                events.append({"type": "halt", "message": f"{wb.label} HALT retired"})

        # EX
        ex = s["EX"]
        flush, target = False, 0
        if ex:
            ins = ex.ins
            a, b = ex.a, ex.b
            if self.forwarding:
                ra, rb = ins.reads()
                a = self._fwd(ra, a, events, ex.label)
                b = self._fwd(rb, b, events, ex.label)
            res = None
            if ins.op in R_OPS:
                res = alu.execute(ins.op, a, b)
            elif ins.op in ("ADDI", "LW", "SW"):
                res = alu.execute("ADD", a, ins.imm)
            elif ins.op in BR_OPS:
                res = alu.execute("SUB", a, b)
                self.branches += 1
                taken = res.zero if ins.op == "BEQ" else not res.zero
                target = ex.pc + 1 + ins.imm
                if taken:
                    self.taken += 1
                    flush = True
                events.append({"type": "branch", "message": f"{ex.label} {ins.op} {'taken -> instruction ' + str(target) if taken else 'not taken'}"})
            if res is not None:
                ex.alu_result = res.result
                alu_info = {"instruction": ex.label, "op": res.op, "a": res.a, "b": res.b, "result": res.result,
                            "zero": res.zero, "negative": res.negative}
            ex.b = b  # store data for SW (after forwarding)

        # MEM
        m = s["MEM"]
        if m:
            try:
                if m.ins.op == "LW":
                    m.wb_value = self.mem.read(m.alu_result)
                    mem_access = {"type": "read", "address": m.alu_result, "value": m.wb_value, "instruction": m.label}
                    events.append({"type": "mem_read", "message": f"{m.label} reads mem[{m.alu_result}] = {m.wb_value}"})
                elif m.ins.op == "SW":
                    self.mem.write(m.alu_result, m.b)
                    mem_access = {"type": "write", "address": m.alu_result, "value": m.b, "instruction": m.label}
                    events.append({"type": "mem_write", "message": f"{m.label} writes mem[{m.alu_result}] = {m.b}"})
                else:
                    m.wb_value = m.alu_result
            except MemoryFault as e:
                self.fault = str(e)
                events.append({"type": "fault", "message": f"{m.label}: {e}"})

        # ID (hazard detection, operand read)
        idn = s["ID"]
        stall = False
        if idn and not flush:
            srcs = idn.ins.sources()
            reason = None
            if self.forwarding:
                if s["EX"] and s["EX"].ins.op == "LW" and s["EX"].ins.dest() in srcs:
                    reason = f"Load-use RAW hazard: {idn.label} needs R{s['EX'].ins.dest()} loaded by {s['EX'].label}"
            else:
                for prod in (s["EX"], s["MEM"]):
                    if prod and prod.ins.dest() in srcs:
                        reason = f"RAW hazard (no forwarding): {idn.label} waits for R{prod.ins.dest()} from {prod.label}"
                        break
            if reason:
                stall = True
                self.stalls += 1
                events.append({"type": "stall", "message": reason})
            else:
                rs, rt = idn.ins.reads()
                idn.a = self.regs.read(rs) if rs is not None else 0
                idn.b = self.regs.read(rt) if rt is not None else 0

        if flush:
            killed = [x for x in (s["IF"], s["ID"]) if x]
            for x in killed:
                x.killed = True
            self.flushes += 1
            self.flushed_instrs += len(killed)
            events.append({"type": "flush", "message": f"Control hazard: pipeline flush, {len(killed)} wrong-path instruction(s) discarded"})

        snapshot = {
            "cycle": self.cycle,
            "pc": self.pc,
            "stages": {"IF": _info(s["IF"], stall), "ID": _info(s["ID"], stall), "EX": _info(s["EX"]),
                       "MEM": _info(s["MEM"]), "WB": _info(s["WB"])},
            "events": events,
            "reg_changes": reg_changes,
            "alu": alu_info,
            "mem_access": mem_access,
        }

        # advance latches
        if flush:
            self.s = {"WB": s["MEM"], "MEM": s["EX"], "EX": None, "ID": None, "IF": None}
            self.pc = target
            self.fetch_stopped = False
        elif stall:
            self.s = {"WB": s["MEM"], "MEM": s["EX"], "EX": None, "ID": s["ID"], "IF": s["IF"]}
        else:
            self.s = {"WB": s["MEM"], "MEM": s["EX"], "EX": s["ID"], "ID": s["IF"], "IF": None}

        snapshot["registers"] = self.regs.snapshot()
        return snapshot
