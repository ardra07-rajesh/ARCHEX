"""Synthetic branch-outcome sequences. Each item is (pc, taken)."""
import random

MAX_BRANCHES = 5000
KINDS = {
    "loop": "A loop branch taken (iterations-1) times then not taken, repeated.",
    "nested_loops": "Inner loop branch (pc 4) inside an outer loop branch (pc 8).",
    "alternating": "Strictly alternating taken / not taken.",
    "biased_random": "Random outcomes with a fixed probability of taken (seeded).",
    "explicit": "User-entered outcome string, e.g. TTNTTN (single branch, pc 4).",
}


class BranchInputError(ValueError):
    def __init__(self, errors: list[dict]):
        super().__init__("; ".join(e["message"] for e in errors))
        self.errors = errors


def generate_branches(w: dict, seed: int) -> list[tuple[int, bool]]:
    kind = w.get("kind", "loop")
    err = lambda f, m: BranchInputError([{"field": f"workload.{f}", "message": m}])  # noqa: E731
    if kind not in KINDS:
        raise err("kind", f"Unknown workload kind '{kind}'")
    if kind == "loop":
        n, r = int(w.get("loop_iterations", 10)), int(w.get("repeats", 5))
        if not (1 <= n <= 1000 and 1 <= r <= 1000):
            raise err("loop_iterations", "loop_iterations and repeats must be 1..1000")
        seq = [(4, k < n - 1) for _ in range(r) for k in range(n)]
    elif kind == "nested_loops":
        o, i = int(w.get("outer", 5)), int(w.get("inner", 4))
        if not (1 <= o <= 200 and 1 <= i <= 200):
            raise err("outer", "outer and inner must be 1..200")
        seq = []
        for a in range(o):
            seq += [(4, k < i - 1) for k in range(i)]
            seq.append((8, a < o - 1))
    elif kind == "alternating":
        seq = [(4, k % 2 == 0) for k in range(int(w.get("count", 40)))]
    elif kind == "biased_random":
        p = float(w.get("p_taken", 0.7))
        if not 0 <= p <= 1:
            raise err("p_taken", "p_taken must be within 0..1")
        rng = random.Random(seed)
        seq = [(4, rng.random() < p) for _ in range(int(w.get("count", 200)))]
    else:
        text = "".join(str(w.get("outcomes", "")).upper().split())
        if not text or set(text) - {"T", "N"}:
            raise err("outcomes", "Enter outcomes using only T (taken) and N (not taken)")
        seq = [(4, c == "T") for c in text]
    if not 1 <= len(seq) <= MAX_BRANCHES:
        raise err("count", f"Workload must contain 1..{MAX_BRANCHES} branches (got {len(seq)})")
    return seq
