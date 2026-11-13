from app.core.events import CATEGORIES, EventBus


def test_summary_counts_only_experiment_events_and_keeps_latest_per_category():
    b = EventBus()
    b.publish("CPU", "run 1", data={"experiment": True, "cycles": 10})
    b.publish("AI", "trained")  # not an experiment
    b.publish("CPU", "run 2", data={"experiment": True, "cycles": 25})
    b.publish("Cache", "run", data={"experiment": True, "hierarchy_hit_ratio": 0.5})
    s = b.summary()
    assert s["experiments"] == 3
    assert s["latest"]["CPU"]["cycles"] == 25 and s["latest"]["Cache"]["hierarchy_hit_ratio"] == 0.5
    assert "AI" not in s["latest"]


def test_empty_bus_has_no_statistics():
    assert EventBus().summary() == {"experiments": 0, "latest": {}}


def test_ids_increase_since_and_clear():
    b = EventBus(maxlen=3)
    for i in range(5):
        b.publish("System", f"e{i}")
    assert [e["id"] for e in b.recent()] == [3, 4, 5]  # ring buffer keeps the newest
    assert [e["id"] for e in b.since(4)] == [5]
    b.clear()
    assert b.recent() == [] and b.publish("System", "x")["id"] == 1


def test_route_categories_are_declared():
    assert {"CPU", "Cache", "Branch", "Timing", "AI", "Defence"} <= set(CATEGORIES)
