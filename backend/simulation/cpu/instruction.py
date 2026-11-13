"""Instruction set and assembler.

Supported: ADD SUB AND OR XOR SLT (R-type), ADDI, LW rd, imm(rs), SW rt, imm(rs),
BEQ/BNE rs, rt, label|offset (offset in instructions, relative to the next instruction), NOP, HALT.
"""
import re
from dataclasses import dataclass

R_OPS = {"ADD", "SUB", "AND", "OR", "XOR", "SLT"}
BR_OPS = {"BEQ", "BNE"}
ALL_OPS = R_OPS | BR_OPS | {"ADDI", "LW", "SW", "NOP", "HALT"}


class AssemblyError(ValueError):
    def __init__(self, errors: list[dict]):
        super().__init__("; ".join(f"line {e['line']}: {e['message']}" for e in errors))
        self.errors = errors


@dataclass(frozen=True)
class Instruction:
    op: str
    rd: int | None = None
    rs: int | None = None
    rt: int | None = None
    imm: int = 0
    text: str = ""
    line: int = 0

    def dest(self) -> int | None:
        if self.op in R_OPS or self.op in ("ADDI", "LW"):
            return self.rd if self.rd else None  # R0 is never a real destination
        return None

    def reads(self) -> tuple[int | None, int | None]:
        if self.op in R_OPS or self.op in ("SW",) or self.op in BR_OPS:
            return self.rs, self.rt
        if self.op in ("ADDI", "LW"):
            return self.rs, None
        return None, None

    def sources(self) -> tuple[int, ...]:
        return tuple(r for r in self.reads() if r)  # None and R0 never cause hazards


_REG = re.compile(r"^[rR](\d+)$")
_MEMREF = re.compile(r"^(-?\w+)\s*\(\s*([rR]\d+)\s*\)$")
_LABEL = re.compile(r"^[A-Za-z_]\w*$")


def _int(tok: str) -> int:
    return int(tok, 0)


def assemble(source: str, num_registers: int = 8) -> list[Instruction]:
    errors: list[dict] = []
    lines: list[tuple[int, str]] = []
    labels: dict[str, int] = {}

    for n, raw in enumerate(source.splitlines(), 1):
        text = re.split(r"[#;]", raw, maxsplit=1)[0].strip()
        while ":" in text:
            lab, text = text.split(":", 1)
            lab, text = lab.strip(), text.strip()
            if not _LABEL.match(lab):
                errors.append({"line": n, "message": f"Invalid label '{lab}'"})
            elif lab in labels:
                errors.append({"line": n, "message": f"Duplicate label '{lab}'"})
            else:
                labels[lab] = len(lines)
        if text:
            lines.append((n, text))

    def reg(tok: str, n: int) -> int | None:
        m = _REG.match(tok.strip())
        if not m or int(m.group(1)) >= num_registers:
            errors.append({"line": n, "message": f"Invalid register '{tok.strip()}' (valid: R0..R{num_registers - 1})"})
            return None
        return int(m.group(1))

    prog: list[Instruction] = []
    for idx, (n, text) in enumerate(lines):
        parts = text.split(None, 1)
        op = parts[0].upper()
        args = [a.strip() for a in parts[1].split(",")] if len(parts) > 1 else []
        canon = f"{op} {', '.join(args)}".strip()

        def need(k: int) -> bool:
            if len(args) != k:
                errors.append({"line": n, "message": f"{op} expects {k} operand(s), got {len(args)}"})
                return False
            return True

        try:
            if op not in ALL_OPS:
                errors.append({"line": n, "message": f"Unknown instruction '{parts[0]}'"})
            elif op in ("NOP", "HALT"):
                if need(0):
                    prog.append(Instruction(op, text=canon, line=n))
            elif op in R_OPS:
                if need(3):
                    prog.append(Instruction(op, rd=reg(args[0], n), rs=reg(args[1], n), rt=reg(args[2], n), text=canon, line=n))
            elif op == "ADDI":
                if need(3):
                    prog.append(Instruction(op, rd=reg(args[0], n), rs=reg(args[1], n), imm=_int(args[2]), text=canon, line=n))
            elif op in ("LW", "SW"):
                if need(2):
                    m = _MEMREF.match(args[1])
                    if not m:
                        errors.append({"line": n, "message": f"{op} second operand must look like 4(R2)"})
                    else:
                        r0, base, off = reg(args[0], n), reg(m.group(2), n), _int(m.group(1))
                        prog.append(Instruction(op, rd=r0, rs=base, imm=off, text=canon, line=n) if op == "LW"
                                    else Instruction(op, rt=r0, rs=base, imm=off, text=canon, line=n))
            else:  # BEQ / BNE
                if need(3):
                    tgt = args[2]
                    if tgt in labels:
                        off = labels[tgt] - (idx + 1)
                    elif _LABEL.match(tgt):
                        errors.append({"line": n, "message": f"Unknown label '{tgt}'"})
                        continue
                    else:
                        off = _int(tgt)
                    if not 0 <= idx + 1 + off <= len(lines):
                        errors.append({"line": n, "message": "Branch target outside program"})
                    prog.append(Instruction(op, rs=reg(args[0], n), rt=reg(args[1], n), imm=off, text=canon, line=n))
        except ValueError:
            errors.append({"line": n, "message": "Immediate values must be integers (decimal or 0x hex)"})

    if not lines and not errors:
        errors.append({"line": 1, "message": "Program is empty"})
    if errors:
        raise AssemblyError(errors)
    return prog
