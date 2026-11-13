"""Deterministic memory-address sequence generators (all synthetic)."""
import random

PATTERNS = {
    "sequential": "Sequential 4-byte scan over the working set, wrapping (spatial locality + reuse once it wraps).",
    "strided": "Fixed-stride scan over the working set, wrapping. Large strides defeat spatial locality.",
    "random": "Uniformly random 4-byte-aligned addresses in the working set (no locality).",
    "hot_cold": "80% of accesses go to the hottest 20% of the working set (temporal locality).",
    "matrix_row": "n x n int matrix traversed row by row (cache friendly).",
    "matrix_col": "n x n int matrix traversed column by column (cache hostile).",
    "explicit": "User-supplied address list.",
}
MAX_ACCESSES = 20000


def generate(w: dict, seed: int) -> list[int]:
    pattern = w.get("pattern", "sequential")
    count = int(w.get("count", 2000))
    ws = int(w.get("working_set_bytes", 8192))
    stride = int(w.get("stride", 4))
    errors = []
    if pattern not in PATTERNS:
        errors.append({"field": "workload.pattern", "message": f"Unknown pattern '{pattern}'"})
    if not 1 <= count <= MAX_ACCESSES:
        errors.append({"field": "workload.count", "message": f"count must be 1..{MAX_ACCESSES}"})
    if ws < 4:
        errors.append({"field": "workload.working_set_bytes", "message": "working_set_bytes must be >= 4"})
    if errors:
        raise ValueError(errors)
    rng = random.Random(seed)
    words = ws // 4
    if pattern == "explicit":
        addrs = [int(a) for a in w.get("addresses", [])]
        if not addrs or len(addrs) > MAX_ACCESSES or any(a < 0 or a >= 2**32 for a in addrs):
            raise ValueError([{"field": "workload.addresses", "message": f"Provide 1..{MAX_ACCESSES} addresses in 0..2^32-1"}])
        return addrs
    if pattern == "sequential":
        return [(i * 4) % ws for i in range(count)]
    if pattern == "strided":
        return [(i * stride) % ws for i in range(count)]
    if pattern == "random":
        return [rng.randrange(words) * 4 for _ in range(count)]
    if pattern == "hot_cold":
        hot = max(1, words // 5)
        return [(rng.randrange(hot) if rng.random() < 0.8 else rng.randrange(words)) * 4 for _ in range(count)]
    n = int(w.get("matrix_dim", 32))
    if not 2 <= n <= 128:
        raise ValueError([{"field": "workload.matrix_dim", "message": "matrix_dim must be 2..128"}])
    if pattern == "matrix_row":
        return [(i * n + j) * 4 for i in range(n) for j in range(n)]
    return [(i * n + j) * 4 for j in range(n) for i in range(n)]
