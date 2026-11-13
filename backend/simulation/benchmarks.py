"""Fixed, seeded benchmark suite computed on demand from the real simulators (no stored or invented numbers)."""
from functools import lru_cache

from app.simulation.branch.predictors import KINDS, run_predictor
from app.simulation.branch.workloads import generate_branches
from app.simulation.cache.cache_engine import compare_caches
from app.simulation.defence.comparison import compare_defences

CACHE_WORKLOADS = {
    "hot_cold": {"pattern": "hot_cold", "count": 4000, "working_set_bytes": 16384},
    "matrix_row": {"pattern": "matrix_row", "matrix_dim": 48},
    "matrix_col": {"pattern": "matrix_col", "matrix_dim": 48},
    "random": {"pattern": "random", "count": 4000, "working_set_bytes": 8192},
}
BRANCH_WORKLOADS = {
    "loop": {"kind": "loop", "loop_iterations": 10, "repeats": 20},
    "nested_loops": {"kind": "nested_loops", "outer": 10, "inner": 5},
    "biased_random": {"kind": "biased_random", "count": 1000, "p_taken": 0.8},
    "alternating": {"kind": "alternating", "count": 200},
}


def _l1(label: str, mapping: str, ways: int, policy: str) -> dict:
    return {"label": label, "memory_latency": 100, "levels": [
        {"size_bytes": 2048, "block_size": 32, "mapping": mapping, "associativity": ways, "policy": policy, "hit_latency": 1}]}


CACHE_CONFIGS = [_l1("Direct", "direct", 1, "LRU"), _l1("2-way LRU", "set_associative", 2, "LRU"), _l1("4-way LRU", "set_associative", 4, "LRU"),
                 _l1("Fully assoc. LRU", "fully_associative", 1, "LRU"), _l1("4-way FIFO", "set_associative", 4, "FIFO"), _l1("4-way Random", "set_associative", 4, "Random")]


def _compute_benchmarks(seed: int = 0) -> dict:
    cache = []
    for name, w in CACHE_WORKLOADS.items():
        r = compare_caches(CACHE_CONFIGS, w, seed)
        cache.append({"workload": name, "accesses": r["workload"]["accesses"], "results": [
            {k: row[k] for k in ("label", "l1_hit_ratio", "l1_miss_ratio", "amat_cycles", "total_cycles", "l1_replacements")} for row in r["results"]]})
    branch = []
    for name, w in BRANCH_WORKLOADS.items():
        seq = generate_branches(w, seed)
        branch.append({"workload": name, "branches": len(seq), "results": [{"predictor": k, **{m: v for m, v in run_predictor(k, seq)["metrics"].items()
                       if m in ("accuracy", "mispredictions", "simulated_cycles")}} for k in KINDS]})
    d = compare_defences(None, {"seed": seed}, include_singles=True, include_recommendations=False)
    defence = {"baseline_distinguishability": d["baseline"]["security"]["distinguishability"], "baseline_cycles": d["baseline"]["performance"]["cycles"],
               "singles": d["single_defences"]}
    return {"data_source": "simulated", "seed": seed, "cache": cache, "branch": branch, "defence": defence}


@lru_cache(maxsize=8)
def run_benchmarks(seed: int = 0) -> dict:
    """Cached benchmark entry point used by the interactive benchmark page."""
    return _compute_benchmarks(seed)


def run_benchmarks_fresh(seed: int = 0) -> dict:
    """Execute the suite without consulting the result cache (for reproducibility checks)."""
    return _compute_benchmarks(seed)
