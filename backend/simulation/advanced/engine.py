"""Advanced branch prediction, shared-cache contention and multi-seed evaluation.

All outputs are simulator results, not measurements of physical processors.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict

from app.simulation.branch.workloads import generate_branches
from app.simulation.cache.cache_engine import CacheConfigError, CacheLevel, normalise_levels
from app.simulation.cache.workloads import generate as generate_addresses


def _sat(value: int, maximum: int = 3) -> int:
    return min(maximum, value + 1) if value < 2 else value


def _update(counter: int, taken: bool, maximum: int = 3) -> int:
    return min(maximum, counter + 1) if taken else max(0, counter - 1)


def run_advanced_predictor(kind: str, sequence: list[tuple[int, bool]], table_size: int = 256, history_bits: int = 8) -> dict:
    if kind not in {"gshare", "tournament"}:
        raise ValueError("predictor must be gshare or tournament")
    if table_size < 16 or table_size > 4096 or table_size & (table_size - 1):
        raise ValueError("table_size must be a power of two in 16..4096")
    if not 2 <= history_bits <= min(16, int(math.log2(table_size))):
        raise ValueError("history_bits must be 2..min(16, log2(table_size))")
    mask, history_mask = table_size - 1, (1 << history_bits) - 1
    global_pht = [1] * table_size
    local_history = defaultdict(int)
    local_pht = [1] * table_size
    chooser = [1] * table_size
    ghr = 0
    correct = 0
    trace = []
    for idx, (pc, actual) in enumerate(sequence):
        pc_index = (pc >> 2) & mask
        g_index = (pc_index ^ ghr) & mask
        g_counter = global_pht[g_index]
        g_prediction = g_counter >= 2
        local_hist = local_history[pc_index] & history_mask
        l_index = ((pc_index << history_bits) ^ local_hist) & mask
        l_prediction = local_pht[l_index] >= 2
        if kind == "gshare":
            prediction = g_prediction
            selected = "global"
        else:
            c = chooser[pc_index]
            prediction = g_prediction if c >= 2 else l_prediction
            selected = "global" if c >= 2 else "local"
        hit = prediction == actual
        correct += int(hit)
        if kind == "tournament" and g_prediction != l_prediction:
            chooser[pc_index] = _update(chooser[pc_index], g_prediction == actual)
        global_pht[g_index] = _update(g_counter, actual)
        local_pht[l_index] = _update(local_pht[l_index], actual)
        local_history[pc_index] = ((local_hist << 1) | int(actual)) & history_mask
        ghr = ((ghr << 1) | int(actual)) & history_mask
        if len(trace) < 1000:
            trace.append({"index": idx, "pc": pc, "actual": actual, "predicted": prediction,
                          "correct": hit, "selected_predictor": selected, "global_history": ghr})
    n = len(sequence)
    misses = n - correct
    return {"predictor": kind, "metrics": {"branches": n, "correct": correct, "mispredictions": misses,
            "accuracy": round(correct / n, 6) if n else None, "misprediction_rate": round(misses / n, 6) if n else None,
            "flush_events": misses}, "config": {"table_size": table_size, "history_bits": history_bits},
            "trace": trace, "trace_truncated": n > len(trace)}


def _cache_cfg(size_bytes: int, block_size: int, associativity: int, policy: str = "LRU") -> dict:
    return {"name": "LLC", "size_bytes": size_bytes, "block_size": block_size,
            "mapping": "set_associative", "associativity": associativity, "policy": policy, "hit_latency": 12}


def run_contention(cores: int, accesses_per_core: int, pattern: str, working_set_bytes: int,
                   cache_size_bytes: int, block_size: int, associativity: int, seed: int) -> dict:
    if not 2 <= cores <= 8:
        raise ValueError("cores must be 2..8")
    if not 32 <= accesses_per_core <= 10000:
        raise ValueError("accesses_per_core must be 32..10000")
    cfg = normalise_levels([_cache_cfg(cache_size_bytes, block_size, associativity)])[0]
    traces = []
    for core in range(cores):
        w = {"pattern": pattern, "count": accesses_per_core, "working_set_bytes": working_set_bytes,
             "stride": block_size, "matrix_dim": max(2, min(64, math.ceil(math.sqrt(accesses_per_core))))}
        try:
            traces.append(generate_addresses(w, seed + core * 997)[:accesses_per_core])
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
    rng = random.Random(seed)
    shared = CacheLevel(cfg, rng)
    per_core = [0] * cores
    per_core_hits = [0] * cores
    interleaved = [(i, core, traces[core][i]) for i in range(accesses_per_core) for core in range(cores)]
    for seq, core, address in interleaved:
        # Private address spaces map to disjoint physical regions in the shared LLC.
        physical = core * (1 << 24) + address
        per_core[core] += 1
        per_core_hits[core] += int(shared.access(physical, seq * cores + core))
    shared_report = shared.report()

    # Simple defence model: invalidate shared cache state on every core switch.
    # This deliberately over-approximates a full cache flush on each context switch.
    flush_cache = CacheLevel(cfg, random.Random(seed))
    flush_hits = 0
    last_core = None
    for seq, core, address in interleaved:
        if last_core is not None and core != last_core:
            flush_cache.flush()
        flush_hits += int(flush_cache.access(core * (1 << 24) + address, seq * cores + core))
        last_core = core

    # Capacity-partitioned baseline: each core receives an equal power-of-two
    # share of the configured aggregate LLC capacity.
    partition_size = 1 << int(math.floor(math.log2(max(block_size, cache_size_bytes // cores))))
    partition_blocks = max(1, partition_size // block_size)
    partition_ways = min(associativity, 1 << int(math.floor(math.log2(partition_blocks))))
    partition_cfg = normalise_levels([_cache_cfg(partition_size, block_size, partition_ways)])[0]
    partition_hits = 0
    partition_misses = 0
    for core in range(cores):
        cache = CacheLevel(partition_cfg, random.Random(seed + core))
        for seq, address in enumerate(traces[core]):
            hit = cache.access(address, seq)
            partition_hits += int(hit)
            partition_misses += int(not hit)

    # Isolated baseline: each core receives a private cache of the same capacity.
    isolated = []
    for core in range(cores):
        cache = CacheLevel(cfg, random.Random(seed + core))
        hits = 0
        for seq, address in enumerate(traces[core]):
            hits += int(cache.access(address, seq))
        isolated.append({"core": core, "hits": hits, "misses": accesses_per_core - hits,
                         "hit_ratio": round(hits / accesses_per_core, 6)})
    rows = [{"core": core, "accesses": per_core[core], "hits": per_core_hits[core],
             "misses": per_core[core] - per_core_hits[core],
             "hit_ratio": round(per_core_hits[core] / per_core[core], 6)} for core in range(cores)]
    total = cores * accesses_per_core
    isolated_misses = sum(x["misses"] for x in isolated)
    shared_misses = shared_report["misses"]
    return {"data_source": "simulated", "deterministic": True,
            "assumptions": ["Round-robin interleaving of per-core synthetic address streams.",
                            "Each core uses a disjoint synthetic physical-address region.",
                            "Shared LLC uses the configured capacity; isolated baseline gives each core a private cache of that same capacity.",
                            "Coherence protocols, prefetchers, out-of-order timing and DRAM queues are not modelled.",
                            "Flush-on-switch is a deliberately simple full-cache invalidation model, not a claim about a particular OS or CPU mitigation.",
                            "Partitioned LLC uses equal power-of-two per-core capacity shares; unused remainder capacity may be lost."],
            "config": {"cores": cores, "accesses_per_core": accesses_per_core, "pattern": pattern,
                       "working_set_bytes": working_set_bytes, "cache": cfg, "seed": seed},
            "summary": {"accesses": total, "shared_hits": shared_report["hits"], "shared_misses": shared_misses,
                        "shared_hit_ratio": round(shared_report["hits"] / total, 6),
                        "isolated_baseline_misses": isolated_misses,
                        "miss_delta_vs_isolated": shared_misses - isolated_misses,
                        "miss_increase_pct_vs_isolated": round((shared_misses - isolated_misses) / isolated_misses * 100, 3) if isolated_misses else 0.0,
                        "flush_on_switch_misses": flush_cache.misses,
                        "flush_on_switch_hit_ratio": round(flush_hits / total, 6),
                        "partitioned_llc_misses": partition_misses,
                        "partitioned_llc_hit_ratio": round(partition_hits / total, 6),
                        "partition_size_bytes_per_core": partition_size},
            "per_core_shared": rows, "per_core_isolated": isolated, "cache": shared_report}


def multi_seed_branch_evaluation(workload: dict, predictor: str, seeds: list[int], table_size: int, history_bits: int) -> dict:
    if not 2 <= len(seeds) <= 50:
        raise ValueError("provide 2..50 seeds")
    values = []
    for seed in seeds:
        seq = generate_branches(workload, seed)
        out = run_advanced_predictor(predictor, seq, table_size, history_bits)
        values.append({"seed": seed, "accuracy": out["metrics"]["accuracy"], "mispredictions": out["metrics"]["mispredictions"]})
    scores = [x["accuracy"] for x in values]
    mean = sum(scores) / len(scores)
    variance = sum((x - mean) ** 2 for x in scores) / (len(scores) - 1)
    sd = math.sqrt(variance)
    half = 1.96 * sd / math.sqrt(len(scores))
    return {"data_source": "simulated", "deterministic": True, "predictor": predictor,
            "runs": values, "statistics": {"n": len(scores), "mean_accuracy": round(mean, 6),
            "sample_std_dev": round(sd, 6), "standard_error": round(sd / math.sqrt(len(scores)), 6),
            "normal_approx_95_ci": [round(max(0, mean - half), 6), round(min(1, mean + half), 6)]},
            "methodology": "Sample mean and sample standard deviation across supplied deterministic seeds; 95% interval uses a normal approximation. This is not a hardware confidence interval."}
