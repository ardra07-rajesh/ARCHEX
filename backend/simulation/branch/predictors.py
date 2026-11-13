"""Dynamic branch predictors: always taken, always not taken, 1-bit, 2-bit saturating counter."""
from .workloads import BranchInputError

KINDS = ("always_taken", "always_not_taken", "one_bit", "two_bit")


class Predictor:
    def __init__(self, kind: str, table_size: int = 16, initial_state: int | None = None):
        if kind not in KINDS:
            raise BranchInputError([{"field": "predictor", "message": f"Unknown predictor '{kind}'"}])
        if table_size < 1 or table_size & (table_size - 1) or table_size > 1024:
            raise BranchInputError([{"field": "table_size", "message": "table_size must be a power of two in 1..1024"}])
        top = {"one_bit": 1, "two_bit": 3}.get(kind)
        init = initial_state if initial_state is not None else {"one_bit": 0, "two_bit": 1}.get(kind, 0)
        if top is not None and not 0 <= init <= top:
            raise BranchInputError([{"field": "initial_state", "message": f"{kind} initial_state must be 0..{top}"}])
        self.kind, self.n = kind, table_size
        self.table = [init] * table_size if top is not None else []

    def _i(self, pc: int) -> int:
        return (pc >> 2) % self.n

    def predict(self, pc: int) -> bool:
        if self.kind == "always_taken":
            return True
        if self.kind == "always_not_taken":
            return False
        s = self.table[self._i(pc)]
        return s >= 1 if self.kind == "one_bit" else s >= 2

    def state(self, pc: int) -> int | None:
        return self.table[self._i(pc)] if self.table else None

    def update(self, pc: int, taken: bool) -> None:
        if not self.table:
            return
        i = self._i(pc)
        if self.kind == "one_bit":
            self.table[i] = 1 if taken else 0
        else:
            self.table[i] = min(3, self.table[i] + 1) if taken else max(0, self.table[i] - 1)


def run_predictor(kind: str, seq: list[tuple[int, bool]], table_size: int = 16, initial_state: int | None = None, penalty: int = 2) -> dict:
    p = Predictor(kind, table_size, initial_state)
    steps, correct = [], 0
    for i, (pc, taken) in enumerate(seq):
        before = p.state(pc)
        pred = p.predict(pc)
        ok = pred == taken
        correct += ok
        p.update(pc, taken)
        steps.append({"i": i, "pc": pc, "actual": taken, "predicted": pred, "correct": ok, "state_before": before,
                      "state_after": p.state(pc), "accuracy": round(correct / (i + 1), 4)})
    n, miss = len(seq), len(seq) - correct
    return {"predictor": kind, "steps": steps, "metrics": {
        "branches": n, "correct": correct, "mispredictions": miss, "accuracy": round(correct / n, 6),
        "misprediction_rate": round(miss / n, 6), "flush_events": miss, "penalty_cycles": miss * penalty,
        "simulated_cycles": n + miss * penalty, "ideal_cycles": n}}
