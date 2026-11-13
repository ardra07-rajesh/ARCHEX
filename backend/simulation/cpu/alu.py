"""32-bit two's-complement ALU."""
from dataclasses import dataclass

MASK = 0xFFFFFFFF


def to_signed(v: int) -> int:
    v &= MASK
    return v - (1 << 32) if v & 0x80000000 else v


@dataclass(frozen=True)
class AluResult:
    op: str
    a: int
    b: int
    result: int
    zero: bool
    negative: bool


def execute(op: str, a: int, b: int) -> AluResult:
    if op == "ADD":
        r = a + b
    elif op == "SUB":
        r = a - b
    elif op == "AND":
        r = a & b
    elif op == "OR":
        r = a | b
    elif op == "XOR":
        r = a ^ b
    elif op == "SLT":
        r = 1 if a < b else 0
    else:
        raise ValueError(f"Unsupported ALU operation: {op}")
    r = to_signed(r)
    return AluResult(op, a, b, r, r == 0, r < 0)
