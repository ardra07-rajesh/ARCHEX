"""Shared experiment execution, activity and serialization services."""
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import VERSION
from app.core.events import bus
from app.database.models import ActivityEvent, Experiment, ExperimentExecution

log = logging.getLogger("archex.research")
RESULT_DIR = Path(__file__).resolve().parents[2] / "data" / "experiment_results"
INLINE_RESULT_LIMIT = 512 * 1024


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def loads(value: str | None, fallback: Any = None) -> Any:
    if not value:
        return {} if fallback is None else fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {} if fallback is None else fallback


def record_event(db: Session, category: str, message: str, severity: str = "info", experiment_id: str | None = None, data: dict | None = None, publish_live: bool = True) -> dict:
    payload = data or {}
    row = ActivityEvent(created_at=now(), category=category, severity=severity, message=message,
                        experiment_id=experiment_id, data_json=dumps(payload))
    db.add(row)
    try:
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Could not persist activity event: %s", category)
    if publish_live:
        return bus.publish(category, message, severity, {**payload, **({"experiment_id": experiment_id} if experiment_id else {})})
    return {"id": row.id, "ts": row.created_at, "category": category, "severity": severity, "message": message}


def load_result(stored: str | None) -> Any:
    """Load an inline result or a large result stored as an immutable JSON artifact."""
    value = loads(stored) if stored else None
    if not isinstance(value, dict) or value.get("_storage") != "file":
        return value
    filename = value.get("file", "")
    if not re.fullmatch(r"[0-9a-f-]{36}\.json", filename):
        raise ValueError("Invalid experiment result artifact reference")
    path = (RESULT_DIR / filename).resolve()
    if path.parent != RESULT_DIR.resolve():
        raise ValueError("Experiment result artifact path is invalid")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.exception("Experiment result artifact is unavailable: %s", filename)
        return {"_result_unavailable": True, "reason": type(exc).__name__, "artifact": filename}


def stored_result(result: dict, execution_id: str) -> str:
    raw = dumps(result)
    raw_bytes = raw.encode("utf-8")
    if len(raw_bytes) <= INLINE_RESULT_LIMIT:
        return raw
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{execution_id}.json"
    destination = RESULT_DIR / filename
    temporary = RESULT_DIR / f".{filename}.tmp"
    temporary.write_bytes(raw_bytes)
    temporary.replace(destination)
    flat = flatten_metrics(result) if isinstance(result, dict) else {}
    summary = {key:value for key,value in list(flat.items())[:100]
               if value is None or isinstance(value, (str, int, float, bool))}
    return dumps({"_storage": "file", "file": filename, "bytes": len(raw_bytes), "summary": summary})


def result_summary(stored: str | None) -> dict:
    """Read compact scalar result metadata without opening a potentially large trace artifact."""
    value = loads(stored) if stored else {}
    if isinstance(value, dict) and value.get("_storage") == "file":
        summary = value.get("summary", {})
        return summary if isinstance(summary, dict) else {}
    if isinstance(value, dict):
        flat = flatten_metrics(value)
        return {key:item for key,item in list(flat.items())[:100]
                if item is None or isinstance(item, (str, int, float, bool))}
    return {}


def delete_result_artifact(stored: str | None) -> None:
    value = loads(stored) if stored else None
    if isinstance(value, dict) and value.get("_storage") == "file":
        filename = value.get("file", "")
        if re.fullmatch(r"[0-9a-f-]{36}\.json", filename):
            path = (RESULT_DIR / filename).resolve()
            if path.parent == RESULT_DIR.resolve():
                try: path.unlink(missing_ok=True)
                except OSError: log.exception("Could not remove experiment artifact %s", filename)


def experiment_dict(row: Experiment, include_result: bool = True) -> dict:
    out = {"id": row.id, "name": row.name, "description": row.description, "category": row.category,
           "simulation": row.simulation, "created_at": row.created_at, "updated_at": row.updated_at,
           "status": row.status, "config": loads(row.config_json), "notes": row.notes,
           "tags": loads(row.tags_json, []), "version": row.version}
    if include_result:
        out["result"] = load_result(row.result_json) if row.result_json else None
    return out


def execution_dict(row: ExperimentExecution, include_result: bool = True) -> dict:
    out = {"id": row.id, "experiment_id": row.experiment_id, "created_at": row.created_at,
           "status": row.status, "config": loads(row.config_json), "error": row.error,
           "duration_ms": row.duration_ms, "software_version": row.software_version,
           "replay_of": row.replay_of}
    if include_result:
        out["result"] = load_result(row.result_json) if row.result_json else None
    return out


def execute(simulation: str, config: dict) -> dict:
    """Dispatch only to the established ARCHEX simulation engines."""
    if simulation == "cpu":
        from app.simulation.cpu.processor import simulate
        return simulate(**config)
    if simulation == "cache":
        from app.simulation.cache.cache_engine import simulate_cache
        return simulate_cache(config["levels"], config.get("memory_latency", 100), config.get("workload", {}), config.get("seed", 0))
    if simulation in ("branch", "speculation"):
        from app.simulation.branch.predictors import KINDS, run_predictor
        from app.simulation.branch.speculation import run_speculation
        from app.simulation.branch.workloads import generate_branches
        workload = config.get("workload", {"kind": "loop"})
        seed = config.get("seed", 0)
        seq = generate_branches(workload, seed)
        predictor = config.get("predictor", "two_bit")
        run = run_predictor(predictor, seq, config.get("table_size", 16), config.get("initial_state"), config.get("mispredict_penalty", 2))
        comparison = [{"predictor": k, **run_predictor(k, seq, config.get("table_size", 16), config.get("initial_state") if k == predictor else None, config.get("mispredict_penalty", 2))["metrics"]} for k in KINDS]
        spec_cfg = config.get("speculation")
        spec = run_speculation(run["steps"], spec_cfg, seed) if simulation == "speculation" and spec_cfg else None
        return {"data_source": "simulated", "deterministic": True, "config": config, "run": run, "comparison": comparison, "speculation": spec}
    if simulation == "side_channel":
        from app.simulation.timing.timing_engine import run_timing_experiment
        return run_timing_experiment(config)
    if simulation == "defence":
        from app.simulation.defence.comparison import compare_defences
        defences = config.get("defences", {})
        params = {k: v for k, v in config.items() if k not in ("defences", "include_singles", "include_recommendations")}
        return compare_defences(defences, params, config.get("include_singles", True), config.get("include_recommendations", True))
    if simulation == "benchmark":
        from app.simulation.benchmarks import run_benchmarks
        return run_benchmarks(config.get("seed", 0))
    raise ValueError(f"Unsupported simulation type: {simulation}")


def execute_and_persist(db: Session, experiment: Experiment, replay_of: str | None = None) -> ExperimentExecution:
    execution_id = str(uuid.uuid4())
    started = time.perf_counter()
    config = loads(experiment.config_json)
    row = ExperimentExecution(id=execution_id, experiment_id=experiment.id, created_at=now(), status="running",
                              config_json=experiment.config_json, replay_of=replay_of, software_version=VERSION)
    db.add(row)
    experiment.status = "running"
    experiment.updated_at = now()
    db.commit()
    record_event(db, "System", f"Experiment {experiment.name} started", experiment_id=experiment.id,
                 data={"execution_id":execution_id,"simulation":experiment.simulation})
    try:
        result = execute(experiment.simulation, config)
        row.result_json = stored_result(result, execution_id)
        row.status = "completed"
        experiment.result_json = row.result_json
        experiment.status = "completed"
        category = {"cpu": "CPU", "cache": "Cache", "branch": "Branch", "speculation": "Branch",
                    "side_channel": "Timing", "defence": "Defence", "benchmark": "System"}.get(experiment.simulation, "System")
        record_event(db, category, f"Experiment {experiment.name} completed", experiment_id=experiment.id,
                     data={"execution_id": execution_id, "simulation": experiment.simulation, "experiment": True})
    except Exception as exc:
        log.exception("Experiment execution failed for %s (%s)", experiment.id, experiment.simulation)
        row.status = "failed"
        row.error = "Execution failed. Check the simulation configuration; detailed diagnostics are in the backend log."
        experiment.status = "failed"
        record_event(db, "System", f"Experiment {experiment.name} failed", "error", experiment.id,
                     {"execution_id": execution_id, "simulation": experiment.simulation})
    finally:
        row.duration_ms = round((time.perf_counter() - started) * 1000, 3)
        experiment.updated_at = now()
        db.commit()
        db.refresh(row)
    return row


def flatten_metrics(value: Any, prefix: str = "", include_lists: bool = False) -> dict[str, Any]:
    """Flatten scalar summary fields; raw trace arrays are excluded unless explicitly exported as JSON."""
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.update(flatten_metrics(v, key, include_lists))
            elif isinstance(v, list):
                if include_lists:
                    out[key] = dumps(v)
            elif v is None or isinstance(v, (str, int, float, bool)):
                out[key] = v
    elif isinstance(value, list) and include_lists:
        out[prefix] = dumps(value)
    else:
        out[prefix] = value
    return out
