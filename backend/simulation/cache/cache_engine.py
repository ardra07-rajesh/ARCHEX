"""Multi-level set-associative cache simulator.

Assumptions (see docs/SIMULATION_METHODOLOGY.md): reads and writes are treated alike (write-allocate, no dirty
bits or write-back traffic); every level allocates on a miss; levels may use different block sizes; latency of an
access is the sum of hit latencies of every level probed plus memory latency if all levels miss.
"""
import random
from collections import OrderedDict

from .workloads import generate

MAX_BLOCKS_PER_LEVEL = 4096


class CacheConfigError(ValueError):
    def __init__(self, errors: list[dict]):
        super().__init__("; ".join(e["message"] for e in errors))
        self.errors = errors


def _pow2(n: int) -> bool:
    return n > 0 and n & (n - 1) == 0


def _validate_level(c: dict, i: int) -> list[dict]:
    p, e = f"levels[{i}]", []
    size, bs = c["size_bytes"], c["block_size"]
    if not _pow2(size):
        e.append({"field": f"{p}.size_bytes", "message": f"{c['name']}: size must be a power of two"})
    if not _pow2(bs) or not 4 <= bs <= 256:
        e.append({"field": f"{p}.block_size", "message": f"{c['name']}: block size must be a power of two in 4..256"})
    if e:
        return e
    if size < bs:
        e.append({"field": f"{p}.size_bytes", "message": f"{c['name']}: size must be at least one block"})
        return e
    nb = size // bs
    if nb > MAX_BLOCKS_PER_LEVEL:
        e.append({"field": f"{p}.size_bytes", "message": f"{c['name']}: at most {MAX_BLOCKS_PER_LEVEL} blocks per level (size/block)"})
    if c["mapping"] == "set_associative" and (not _pow2(c["associativity"]) or c["associativity"] > nb):
        e.append({"field": f"{p}.associativity", "message": f"{c['name']}: associativity must be a power of two <= {nb}"})
    if c["hit_latency"] < 1:
        e.append({"field": f"{p}.hit_latency", "message": f"{c['name']}: hit latency must be >= 1 cycle"})
    return e


class _Way:
    __slots__ = ("valid", "tag", "block", "inserted", "last_used", "count")

    def __init__(self):
        self.valid, self.tag, self.block, self.inserted, self.last_used, self.count = False, 0, 0, 0, 0, 0


class CacheLevel:
    def __init__(self, cfg: dict, rng: random.Random):
        self.name, self.policy, self.mapping = cfg["name"], cfg["policy"], cfg["mapping"]
        self.size, self.block_size, self.hit_latency = cfg["size_bytes"], cfg["block_size"], cfg["hit_latency"]
        self.nblocks = self.size // self.block_size
        self.ways = 1 if self.mapping == "direct" else self.nblocks if self.mapping == "fully_associative" else cfg["associativity"]
        self.nsets = self.nblocks // self.ways
        self.offset_bits = self.block_size.bit_length() - 1
        self.index_bits = self.nsets.bit_length() - 1
        self.sets = [[_Way() for _ in range(self.ways)] for _ in range(self.nsets)]
        self.rng = rng
        self.set_acc = [0] * self.nsets
        self.accesses = self.hits = self.misses = self.replacements = 0
        self.compulsory = self.capacity = self.conflict = 0
        self.seen: set[int] = set()
        self.shadow: OrderedDict[int, bool] = OrderedDict()  # fully-associative LRU of equal capacity (3C model)

    def access(self, addr: int, seq: int) -> bool:
        block = addr >> self.offset_bits
        s, tag = block % self.nsets, block // self.nsets
        self.accesses += 1
        self.set_acc[s] += 1
        first = block not in self.seen
        self.seen.add(block)
        shadow_hit = block in self.shadow
        if shadow_hit:
            self.shadow.move_to_end(block)
        else:
            self.shadow[block] = True
            if len(self.shadow) > self.nblocks:
                self.shadow.popitem(last=False)

        ways = self.sets[s]
        for w in ways:
            if w.valid and w.tag == tag:
                w.last_used, w.count = seq, w.count + 1
                self.hits += 1
                return True

        self.misses += 1
        if first:
            self.compulsory += 1
        elif not shadow_hit:
            self.capacity += 1
        else:
            self.conflict += 1

        victim = next((w for w in ways if not w.valid), None)
        if victim is None:
            if self.policy == "FIFO":
                victim = min(ways, key=lambda w: w.inserted)
            elif self.policy == "LRU":
                victim = min(ways, key=lambda w: w.last_used)
            else:
                victim = self.rng.choice(ways)
            self.replacements += 1
        victim.valid, victim.tag, victim.block = True, tag, block
        victim.inserted = victim.last_used = seq
        victim.count = 1
        return False

    def flush(self) -> None:
        """Invalidate every line (counters are left untouched)."""
        for ways in self.sets:
            for w in ways:
                w.valid = False

    def contains(self, addr: int) -> bool:
        """Presence check with no state change."""
        block = addr >> self.offset_bits
        s, tag = block % self.nsets, block // self.nsets
        return any(w.valid and w.tag == tag for w in self.sets[s])

    def contains(self, addr: int) -> bool:
        """Non-allocating probe: does not change any state or counter."""
        block = addr >> self.offset_bits
        s, tag = block % self.nsets, block // self.nsets
        return any(w.valid and w.tag == tag for w in self.sets[s])

    def report(self) -> dict:
        ratio = lambda x: round(x / self.accesses, 6) if self.accesses else None  # noqa: E731
        return {
            "name": self.name,
            "config": {"size_bytes": self.size, "block_size": self.block_size, "mapping": self.mapping, "ways": self.ways,
                       "sets": self.nsets, "policy": self.policy, "hit_latency": self.hit_latency,
                       "offset_bits": self.offset_bits, "index_bits": self.index_bits},
            "accesses": self.accesses, "hits": self.hits, "misses": self.misses,
            "hit_ratio": ratio(self.hits), "miss_ratio": ratio(self.misses), "replacements": self.replacements,
            "miss_breakdown": {"compulsory": self.compulsory, "capacity": self.capacity, "conflict": self.conflict},
            "set_access_counts": self.set_acc,
            "blocks": [[{"valid": w.valid, "tag": w.tag, "block_addr": w.block << self.offset_bits if w.valid else None,
                         "count": w.count} for w in ways] for ways in self.sets],
        }


def normalise_levels(levels: list[dict]) -> list[dict]:
    if not 1 <= len(levels) <= 3:
        raise CacheConfigError([{"field": "levels", "message": "Provide 1 to 3 cache levels"}])
    out, errs = [], []
    for i, lv in enumerate(levels):
        c = {"name": f"L{i + 1}", "mapping": "set_associative", "associativity": 4, "policy": "LRU", "hit_latency": 1, **lv}
        c["name"] = c.get("name") or f"L{i + 1}"
        errs += _validate_level(c, i)
        out.append(c)
    if errs:
        raise CacheConfigError(errs)
    return out


def simulate_cache(levels: list[dict], memory_latency: int, workload: dict, seed: int = 0, *, addresses: list[int] | None = None) -> dict:
    cfgs = normalise_levels(levels)
    if memory_latency < 1:
        raise CacheConfigError([{"field": "memory_latency", "message": "memory_latency must be >= 1 cycle"}])
    if addresses is None:
        try:
            addresses = generate(workload, seed)
        except ValueError as e:
            raise CacheConfigError(e.args[0]) from e

    rng = random.Random(seed)
    lv = [CacheLevel(c, rng) for c in cfgs]
    n = len(addresses)
    total_latency = mem_accesses = 0
    log, series = [], []
    step = max(1, n // 200)
    served_any = 0
    l1_hits = 0
    for i, a in enumerate(addresses):
        lat, served = 0, "MEM"
        for L in lv:
            lat += L.hit_latency
            if L.access(a, i):
                served = L.name
                break
        else:
            lat += memory_latency
            mem_accesses += 1
        total_latency += lat
        if served != "MEM":
            served_any += 1
        if served == lv[0].name:
            l1_hits += 1
        if i < 500:
            log.append({"i": i, "address": a, "served_by": served, "latency": lat})
        if i % step == 0 or i == n - 1:
            series.append({"access": i + 1, "l1_hit_ratio": round(l1_hits / (i + 1), 4), "hierarchy_hit_ratio": round(served_any / (i + 1), 4)})

    # Analytical AMAT from local miss ratios; must equal the measured mean latency.
    amat = float(memory_latency)
    for L in reversed(lv):
        m = L.misses / L.accesses if L.accesses else 0.0
        amat = L.hit_latency + m * amat
    return {
        "data_source": "simulated", "deterministic": True,
        "config": {"levels": cfgs, "memory_latency": memory_latency, "seed": seed},
        "workload": {**{k: v for k, v in workload.items() if k != "addresses"}, "accesses": n, "unique_blocks_l1": len(lv[0].seen)},
        "summary": {
            "accesses": n, "hierarchy_hits": served_any, "memory_accesses": mem_accesses,
            "hierarchy_hit_ratio": round(served_any / n, 6),
            "amat_cycles": round(amat, 6), "measured_avg_latency_cycles": round(total_latency / n, 6),
            "total_cycles": total_latency, "speedup_vs_no_cache": round(memory_latency * n / total_latency, 4),
        },
        "levels": [L.report() for L in lv],
        "access_log": log, "hit_ratio_series": series,
    }


def compare_caches(configs: list[dict], workload: dict, seed: int = 0) -> dict:
    """Run several configurations on the identical address sequence."""
    try:
        addrs = generate(workload, seed)
    except ValueError as e:
        raise CacheConfigError(e.args[0]) from e
    rows = []
    for k, c in enumerate(configs):
        r = simulate_cache(c["levels"], c.get("memory_latency", 100), workload, seed, addresses=addrs)
        l1 = r["levels"][0]
        rows.append({"label": c.get("label") or f"Config {k + 1}", "l1_hit_ratio": l1["hit_ratio"], "l1_miss_ratio": l1["miss_ratio"],
                     "l1_replacements": l1["replacements"], "miss_breakdown": l1["miss_breakdown"],
                     "hierarchy_hit_ratio": r["summary"]["hierarchy_hit_ratio"], "amat_cycles": r["summary"]["amat_cycles"],
                     "total_cycles": r["summary"]["total_cycles"], "speedup_vs_no_cache": r["summary"]["speedup_vs_no_cache"],
                     "config": r["config"]})
    return {"data_source": "simulated", "workload": {**{k: v for k, v in workload.items() if k != "addresses"}, "accesses": len(addrs)},
            "seed": seed, "results": rows}
