"""In-process event bus (ring buffer, current server session only).

Events are published by the API routes after a simulation or analysis really completed; nothing is
seeded or invented. Persistence arrives with the experiment store (Phase 8)."""
import threading
from collections import deque
from datetime import datetime, timezone

CATEGORIES = ("CPU", "Cache", "Memory", "Branch", "Timing", "AI", "Defence", "System")


class EventBus:
    def __init__(self, maxlen: int = 1000):
        self._lock = threading.Lock()
        self._events: deque = deque(maxlen=maxlen)
        self._next = 1

    def publish(self, category: str, message: str, severity: str = "info", data: dict | None = None) -> dict:
        with self._lock:
            ev = {"id": self._next, "ts": datetime.now(timezone.utc).isoformat(), "category": category, "severity": severity,
                  "message": message, "data": data or {}}
            self._next += 1
            self._events.append(ev)
            return ev

    def since(self, last_id: int) -> list[dict]:
        with self._lock:
            return [e for e in self._events if e["id"] > last_id]

    def recent(self, limit: int = 100) -> list[dict]:
        with self._lock:
            return list(self._events)[-limit:]

    def summary(self) -> dict:
        """Session statistics derived only from published events.

        experiments: events flagged data["experiment"] (a completed simulation or analysis).
        latest: per category, the data of the most recent experiment event.
        """
        with self._lock:
            events = list(self._events)
        experiments = [e for e in events if e["data"].get("experiment")]
        latest: dict[str, dict] = {}
        for e in experiments:
            latest[e["category"]] = e["data"]
        return {"experiments": len(experiments), "latest": latest}

    def clear(self) -> None:
        """Test helper: drop all events and restart ids."""
        with self._lock:
            self._events.clear()
            self._next = 1


bus = EventBus()
