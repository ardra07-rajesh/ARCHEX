"""Controlled, educational speculative-execution model (synthetic addresses, no secrets).

On every misprediction the wrong path speculatively issues `spec_loads` loads to a synthetic wrong-path region.
Architectural state is rolled back, but those loads have already allocated cache lines (microarchitectural residue).
The `restricted` variant models a speculation restriction: wrong-path loads never allocate cache lines.
"""
import random

from app.simulation.cache.cache_engine import CacheLevel, normalise_levels

WRONG_BASE = 0x100000
WRONG_LINES = 64


def _variant(steps: list[dict], sp: dict, restrict: bool, seed: int) -> dict:
    cfg = normalise_levels([{"size_bytes": sp["cache_size_bytes"], "block_size": sp["block_size"], "mapping": "set_associative",
                             "associativity": sp["associativity"], "policy": "LRU", "hit_latency": 1}])[0]
    cache = CacheLevel(cfg, random.Random(seed))
    bs = sp["block_size"]
    ws_blocks = max(1, sp["working_set_bytes"] // bs)
    seq = k = hits = loads = fills = wp = squashed = 0
    wrong: list[int] = []
    for st in steps:
        for _ in range(sp["loads_per_branch"]):
            loads += 1
            hits += cache.access((k % ws_blocks) * bs, seq)
            k, seq = k + 1, seq + 1
        if not st["correct"]:
            squashed += sp["window"]
            for _ in range(sp["spec_loads"]):
                a = WRONG_BASE + (wp % WRONG_LINES) * bs
                wp += 1
                wrong.append(a)
                if not restrict:
                    fills += 0 if cache.access(a, seq) else 1
                    seq += 1
    probe = sorted(set(wrong))
    residue = sum(cache.contains(a) for a in probe)
    return {"correct_path_loads": loads, "correct_path_hits": hits, "correct_path_hit_ratio": round(hits / loads, 6) if loads else None,
            "squashed_instructions": squashed, "speculative_cache_fills": fills, "wrong_path_lines": len(probe), "residual_lines_in_cache": residue}


def run_speculation(steps: list[dict], sp: dict, seed: int = 0) -> dict:
    allowed, restricted = _variant(steps, sp, False, seed), _variant(steps, sp, True, seed)
    delta = None
    if allowed["correct_path_hit_ratio"] is not None:
        delta = round(restricted["correct_path_hit_ratio"] - allowed["correct_path_hit_ratio"], 6)
    return {"config": sp, "speculation_allowed": allowed, "speculation_restricted": restricted, "hit_ratio_cost_of_speculation": delta,
            "note": "Synthetic model: wrong-path addresses are fixed synthetic lines, not derived from any secret."}
