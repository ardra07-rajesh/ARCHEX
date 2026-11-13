import pytest

from app.simulation.cache.cache_engine import CacheConfigError, compare_caches, simulate_cache

EXPLICIT = lambda a: {"pattern": "explicit", "addresses": a}  # noqa: E731


def lvl(size, bs, mapping="set_associative", ways=2, policy="LRU", lat=1):
    return {"size_bytes": size, "block_size": bs, "mapping": mapping, "associativity": ways, "policy": policy, "hit_latency": lat}


def run(levels, addrs, mem=100, seed=0):
    return simulate_cache(levels, mem, EXPLICIT(addrs), seed)


def test_direct_mapped_conflict_misses_vs_associative():
    pingpong = [0, 64] * 10  # blocks 0 and 4 collide in a 4-set direct-mapped cache
    dm = run([lvl(64, 16, "direct")], pingpong)["levels"][0]
    assert dm["hits"] == 0 and dm["miss_breakdown"] == {"compulsory": 2, "capacity": 0, "conflict": 18}
    assert run([lvl(64, 16, "set_associative", 2)], pingpong)["levels"][0]["hits"] == 18
    assert run([lvl(64, 16, "fully_associative")], pingpong)["levels"][0]["hits"] == 18


def test_lru_beats_fifo_on_classic_sequence():
    seq = [0, 16, 0, 32, 0]  # A B A C A in a 2-block fully-associative cache
    lru = run([lvl(32, 16, "fully_associative", policy="LRU")], seq)["levels"][0]
    fifo = run([lvl(32, 16, "fully_associative", policy="FIFO")], seq)["levels"][0]
    assert lru["hits"] == 2 and fifo["hits"] == 1
    assert lru["replacements"] == 1 and fifo["replacements"] == 2


def test_spatial_locality_sequential_scan():
    r = run([lvl(4096, 16, ways=4)], [i * 4 for i in range(64)])["levels"][0]
    assert r["hit_ratio"] == 0.75 and r["miss_breakdown"]["compulsory"] == 16


def test_amat_formula_matches_measured_latency():
    r = simulate_cache([lvl(256, 16, ways=2, lat=1), lvl(1024, 32, ways=4, lat=10), lvl(8192, 64, ways=8, lat=30)], 100,
                       {"pattern": "random", "count": 3000, "working_set_bytes": 6000}, seed=5)
    s = r["summary"]
    assert abs(s["amat_cycles"] - s["measured_avg_latency_cycles"]) < 1e-3
    assert s["total_cycles"] == round(s["measured_avg_latency_cycles"] * s["accesses"])  or abs(s["total_cycles"] - s["measured_avg_latency_cycles"] * s["accesses"]) < 3
    assert r["levels"][1]["accesses"] == r["levels"][0]["misses"]  # L2 only sees L1 misses


def test_seeded_random_policy_is_deterministic():
    w = {"pattern": "random", "count": 2000, "working_set_bytes": 4096}
    a = simulate_cache([lvl(256, 16, policy="Random")], 100, w, seed=9)
    b = simulate_cache([lvl(256, 16, policy="Random")], 100, w, seed=9)
    assert a == b


def test_matrix_row_major_beats_column_major():
    def hit(p):
        return simulate_cache([lvl(1024, 32, ways=2)], 100, {"pattern": p, "matrix_dim": 64}, 0)["levels"][0]["hit_ratio"]
    assert hit("matrix_row") == 0.875 and hit("matrix_col") < 0.2


def test_invalid_configs_rejected():
    with pytest.raises(CacheConfigError):
        run([lvl(1000, 32)], [0])
    with pytest.raises(CacheConfigError):
        run([lvl(64, 16, ways=3)], [0])
    with pytest.raises(CacheConfigError):
        simulate_cache([lvl(64, 16)], 100, {"pattern": "bogus"}, 0)


def test_compare_uses_identical_addresses():
    cfgs = [{"label": p, "levels": [lvl(256, 16, ways=2, policy=p)]} for p in ("FIFO", "LRU", "Random")]
    r = compare_caches(cfgs, {"pattern": "hot_cold", "count": 3000, "working_set_bytes": 4096}, seed=2)
    assert len(r["results"]) == 3 and r["workload"]["accesses"] == 3000
