import json
from sqlalchemy import delete
from fastapi.testclient import TestClient
import pytest
from app.main import app
from app.database.session import SessionLocal
from app.database.models import Experiment, ExperimentExecution, ActivityEvent, ResearchReport

client = TestClient(app)

@pytest.fixture(autouse=True)
def isolate_research_records():
    clear_research()
    yield
    clear_research()

def clear_research():
    with SessionLocal() as db:
        for model in (ResearchReport, ExperimentExecution, ActivityEvent, Experiment):
            db.execute(delete(model))
        db.commit()

def test_experiment_create_run_history_duplicate_patch_delete_and_replay():
    clear_research()
    body={"name":"CPU regression baseline","description":"Pipeline smoke test","category":"cpu","simulation":"cpu","config":{"program":"ADDI R1, R0, 9\nHALT","num_registers":8,"forwarding":True,"max_cycles":2000,"memory_size_words":256,"clock_mhz":100},"tags":["smoke"]}
    created=client.post("/api/v1/research/experiments",json=body); assert created.status_code==200,created.text
    eid=created.json()["id"]
    run=client.post(f"/api/v1/research/experiments/{eid}/run"); assert run.status_code==200,run.text
    assert run.json()["execution"]["status"]=="completed"
    assert run.json()["execution"]["result"]["final_registers"][1]==9
    history=client.get(f"/api/v1/research/experiments/{eid}/executions").json(); assert len(history)==1
    replay=client.post(f"/api/v1/research/executions/{history[0]['id']}/replay"); assert replay.status_code==200,replay.text
    assert replay.json()["execution"]["replay_of"]==history[0]["id"]
    assert replay.json()["execution"]["id"]!=history[0]["id"]
    assert "same_result" in replay.json()["comparison"]
    duplicate=client.post(f"/api/v1/research/experiments/{eid}/duplicate"); assert duplicate.status_code==200
    assert duplicate.json()["status"]=="draft" and duplicate.json()["result"] is None
    patched=client.patch(f"/api/v1/research/experiments/{eid}",json={"notes":"Updated methodology"}); assert patched.status_code==200
    assert patched.json()["version"]==2
    assert client.get("/api/v1/research/experiments?q=CPU&tag=smoke").json()["total"]==2
    assert client.get("/api/v1/research/activity").json()["events"]
    assert client.delete(f"/api/v1/research/experiments/{eid}").json()["deleted"] is True

def test_compare_requires_completed_results_and_returns_shared_numeric_fields():
    clear_research()
    body={"name":"CPU baseline","simulation":"cpu","config":{"program":"ADDI R1, R0, 2\nHALT","num_registers":8,"forwarding":True,"max_cycles":2000,"memory_size_words":256,"clock_mhz":100}}
    ids=[]
    for name in ("A","B"):
        b={**body,"name":name}; eid=client.post("/api/v1/research/experiments",json=b).json()["id"]; ids.append(eid)
        assert client.post(f"/api/v1/research/experiments/{eid}/run").status_code==200
    result=client.post("/api/v1/research/compare",json=ids); assert result.status_code==200,result.text
    assert "metrics" in result.json() and result.json()["experiments"]

def test_workbench_dispatches_existing_engine_families():
    clear_research()
    configs={
      "cache":{"levels":[{"name":"L1","size_bytes":1024,"block_size":32,"mapping":"set_associative","associativity":2,"policy":"LRU","hit_latency":1}],"memory_latency":100,"workload":{"pattern":"sequential","count":64,"stride":4,"working_set_bytes":1024,"matrix_dim":8},"seed":2},
      "branch":{"predictor":"two_bit","workload":{"kind":"loop","loop_iterations":4,"repeats":2},"table_size":16,"mispredict_penalty":2,"seed":2},
      "speculation":{"predictor":"two_bit","workload":{"kind":"loop","loop_iterations":4,"repeats":2},"table_size":16,"mispredict_penalty":2,"speculation":{"window":8,"spec_loads":2,"loads_per_branch":1,"working_set_bytes":256,"cache_size_bytes":256,"block_size":32,"associativity":8},"seed":2},
      "side_channel":{"samples":100,"seed":2,"hit_latency_mean":40,"miss_latency_mean":200,"jitter_std":15,"defence":None},
      "defence":{"defences":{"cache_partitioning":False,"memory_isolation":False,"cache_flushing":False,"constant_time":False,"speculation_restriction":False,"timing_noise_std":0},"rounds":40,"perf_accesses":500,"seed":2,"jitter_std":30,"p_spec":0.5,"spec_lines":4,"include_singles":True,"include_recommendations":True},
      "benchmark":{"seed":2}}
    for sim,config in configs.items():
      created=client.post("/api/v1/research/experiments",json={"name":f"dispatch {sim}","simulation":sim,"config":config}); assert created.status_code==200,f"{sim}: {created.text}"
      run=client.post(f"/api/v1/research/experiments/{created.json()['id']}/run"); assert run.status_code==200,f"{sim}: {run.text}"

def test_assistant_accepts_saved_experiment_context():
    clear_research()
    exp=client.post("/api/v1/research/experiments",json={"name":"Context experiment","simulation":"cpu","config":{"program":"HALT","num_registers":8,"forwarding":True,"max_cycles":100,"memory_size_words":64,"clock_mhz":100}}).json()
    conv=client.post("/api/v1/assistant/conversations",json={"title":"Experiment context"}).json()
    reply=client.post(f"/api/v1/assistant/conversations/{conv['id']}/messages",json={"message":"Summarise this experiment","context_experiment_id":exp["id"]})
    assert reply.status_code==200,reply.text
    history=client.get(f"/api/v1/assistant/conversations/{conv['id']}").json()
    assert history["messages"][-1]["context"]["scope"]=="selected_saved_experiment"

def test_large_results_are_offloaded_to_immutable_artifacts():
    from app.services.research import stored_result, load_result, delete_result_artifact
    import uuid
    execution_id=str(uuid.uuid4())
    payload={"trace":["sample"*100 for _ in range(1200)],"metrics":{"cycles":42}}
    stored=stored_result(payload,execution_id)
    pointer=json.loads(stored)
    assert pointer["_storage"]=="file" and pointer["bytes"]>512*1024
    assert load_result(stored)==payload
    delete_result_artifact(stored)

def test_comparison_rejects_mixed_simulation_families():
    clear_research()
    cpu=client.post("/api/v1/research/experiments",json={"name":"CPU","simulation":"cpu","config":{"program":"HALT","num_registers":8,"forwarding":True,"max_cycles":100,"memory_size_words":64,"clock_mhz":100}}).json()
    cache=client.post("/api/v1/research/experiments",json={"name":"Cache","simulation":"cache","config":{"levels":[{"size_bytes":128,"block_size":16,"associativity":1}],"workload":{"pattern":"sequential","count":10}}}).json()
    assert client.post("/api/v1/research/compare",json=[cpu["id"],cache["id"]]).status_code==409


def test_operations_enriches_execution_and_activity_includes_session_events():
    from app.core.events import bus
    clear_research()
    created=client.post("/api/v1/research/experiments",json={"name":"Operations CPU","simulation":"cpu","config":{"program":"HALT","num_registers":8,"forwarding":True,"max_cycles":100,"memory_size_words":64,"clock_mhz":100}}).json()
    assert client.post(f"/api/v1/research/experiments/{created['id']}/run").status_code==200
    ops=client.get("/api/v1/research/operations").json()
    assert ops["recent"][0]["experiment_name"]=="Operations CPU"
    assert ops["recent"][0]["simulation"]=="cpu"
    bus.publish("CPU","Direct lab run completed",data={"experiment":True})
    events=client.get("/api/v1/research/activity").json()["events"]
    assert any(e["message"]=="Direct lab run completed" and e["source"]=="session" for e in events)

def test_dashboard_uses_saved_experiment_metrics_after_session_bus_reset():
    from app.core.events import bus
    clear_research()
    config={"levels":[{"name":"L1","size_bytes":256,"block_size":16,"mapping":"direct","associativity":1,"policy":"LRU","hit_latency":1}],"memory_latency":50,"workload":{"pattern":"sequential","count":40,"stride":4,"working_set_bytes":256},"seed":9}
    exp=client.post("/api/v1/research/experiments",json={"name":"Persisted cache metrics","simulation":"cache","config":config}).json()
    assert client.post(f"/api/v1/research/experiments/{exp['id']}/run").status_code==200
    bus.clear()
    summary=client.get("/api/v1/dashboard/summary").json()
    kpis={item["key"]:item["value"] for item in summary["kpis"]}
    assert kpis["experiments"]==1
    assert kpis["cache_hit_ratio"] is not None
    assert summary["recent_experiments"][0]["name"]=="Persisted cache metrics"
    assert summary["execution_counts"]["completed"]==1
