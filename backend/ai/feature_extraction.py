import math
import statistics
from collections import Counter

from app.simulation.branch.predictors import run_predictor
from app.simulation.cache.cache_engine import simulate_cache

FEATURES = ["cache_hit_ratio", "cache_miss_ratio", "avg_access_latency", "timing_variance", "branch_accuracy",
            "misprediction_frequency", "memory_access_frequency", "execution_cycles", "access_pattern_irregularity"]
FEATURE_UNITS = {
    "cache_hit_ratio": "L1 hits / accesses", "cache_miss_ratio": "accesses reaching memory / accesses",
    "avg_access_latency": "cycles", "timing_variance": "cycles^2", "branch_accuracy": "fraction",
    "misprediction_frequency": "mispredictions per 1000 instructions", "memory_access_frequency": "accesses per cycle",
    "execution_cycles": "cycles", "access_pattern_irregularity": "normalised delta entropy 0..1",
}
# Fixed measurement hierarchy used for every trace (same hardware model for every scenario).
LEVELS = [
    {"name": "L1", "size_bytes": 2048, "block_size": 32, "mapping": "set_associative", "associativity": 4, "policy": "LRU", "hit_latency": 1},
    {"name": "L2", "size_bytes": 16384, "block_size": 64, "mapping": "set_associative", "associativity": 8, "policy": "LRU", "hit_latency": 10},
]
MEMORY_LATENCY = 100
BRANCH_PENALTY = 2


def _irregularity(addrs: list[int]) -> float:
    blocks = [a // 32 for a in addrs]
    deltas = [b - a for a, b in zip(blocks, blocks[1:])]
    if len(deltas) < 2:
        return 0.0
    counts = Counter(deltas)
    n = len(deltas)
    h = -sum(c / n * math.log2(c / n) for c in counts.values())
    return h / math.log2(n)


def extract_features(trace: dict) -> dict[str, float]:
    addrs = trace["addresses"]
    cache = simulate_cache(LEVELS, MEMORY_LATENCY, {"pattern": "explicit", "addresses": addrs}, seed=0)
    br = run_predictor("two_bit", [tuple(b) for b in trace["branches"]], 16, None, BRANCH_PENALTY)["metrics"]
    lat = [x["latency"] for x in cache["access_log"]]  # log covers up to the first 500 accesses
    s, l1 = cache["summary"], cache["levels"][0]
    cycles = s["total_cycles"] + br["simulated_cycles"]
    instr = len(addrs) + br["branches"]
    return {
        "cache_hit_ratio": l1["hit_ratio"],
        "cache_miss_ratio": 1 - s["hierarchy_hit_ratio"],
        "avg_access_latency": s["measured_avg_latency_cycles"],
        "timing_variance": statistics.pvariance(lat),
        "branch_accuracy": br["accuracy"],
        "misprediction_frequency": 1000 * br["mispredictions"] / instr,
        "memory_access_frequency": len(addrs) / cycles,
        "execution_cycles": float(cycles),
        "access_pattern_irregularity": _irregularity(addrs),
    }
