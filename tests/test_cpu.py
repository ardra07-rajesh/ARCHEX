import pytest

from app.simulation.cpu.alu import execute, to_signed
from app.simulation.cpu.instruction import AssemblyError, assemble
from app.simulation.cpu.processor import SimulationInputError, simulate
from app.simulation.cpu.workloads import SAMPLE_WORKLOADS


def test_alu_wraps_32_bit_and_flags():
    assert execute("ADD", 2**31 - 1, 1).result == -(2**31)
    r = execute("SUB", 5, 5)
    assert r.zero and not r.negative
    assert execute("SLT", -1, 0).result == 1
    assert to_signed(0xFFFFFFFF) == -1


def test_assembler_reports_line_numbers():
    with pytest.raises(AssemblyError) as e:
        assemble("ADDI R1, R0, 1\nFOO R1\nADD R1, R9, R1", 8)
    lines = [x["line"] for x in e.value.errors]
    assert lines == [2, 3]


def test_assembler_labels_and_offsets():
    prog = assemble("top:\nADDI R1, R0, 1\nBEQ R0, R0, top\nHALT")
    assert prog[1].imm == -2


def test_straight_line_takes_n_plus_4_cycles():
    r = simulate("ADDI R1, R0, 1\nADDI R2, R0, 2\nADDI R3, R0, 3\nHALT")
    m = r["metrics"]
    assert r["status"] == "halted"
    assert m["instructions_retired"] == 4 and m["cycles"] == 8 and m["stall_cycles"] == 0


def test_r0_is_immutable():
    r = simulate("ADDI R0, R0, 5\nADD R1, R0, R0\nHALT")
    assert r["final_registers"][0] == 0 and r["final_registers"][1] == 0


def test_forwarding_removes_raw_stalls_and_keeps_results():
    prog = SAMPLE_WORKLOADS["raw_chain"]["program"]
    fw = simulate(prog, forwarding=True)
    nofw = simulate(prog, forwarding=False)
    assert fw["metrics"]["stall_cycles"] == 0 and fw["metrics"]["forwarding_events"] > 0
    assert nofw["metrics"]["stall_cycles"] > 0
    assert fw["final_registers"] == nofw["final_registers"]
    assert fw["final_registers"][2:5] == [6, 9, 15]
    assert nofw["metrics"]["cycles"] > fw["metrics"]["cycles"]


def test_load_use_costs_exactly_one_stall_with_forwarding():
    r = simulate(SAMPLE_WORKLOADS["load_use"]["program"])
    assert r["metrics"]["stall_cycles"] == 1
    assert r["final_registers"][3] == 84
    assert r["final_memory"] == {"0": 42}


def test_loop_computes_sum_and_flushes_each_taken_branch():
    r = simulate(SAMPLE_WORKLOADS["loop_sum"]["program"])
    m = r["metrics"]
    assert r["final_registers"][2] == 15
    assert m["branches"] == 5 and m["branches_taken"] == 4
    assert m["flush_events"] == 4
    # Each flush costs 2 cycles of lost work => cycles = retired + 4 + 2*flushes (no other stalls here)
    assert m["cycles"] == m["instructions_retired"] + 4 + 2 * m["flush_events"] + m["stall_cycles"]


def test_results_identical_with_and_without_forwarding_for_all_samples():
    for name, w in SAMPLE_WORKLOADS.items():
        a = simulate(w["program"], forwarding=True)
        b = simulate(w["program"], forwarding=False)
        assert a["status"] == b["status"] == "halted", name
        assert a["final_registers"] == b["final_registers"], name
        assert a["final_memory"] == b["final_memory"], name


def test_memory_traffic_sample():
    r = simulate(SAMPLE_WORKLOADS["mem_traffic"]["program"])
    assert r["final_registers"][7] == 33 and r["final_memory"] == {"0": 11, "4": 22, "8": 33}


def test_memory_fault_is_reported():
    r = simulate("ADDI R1, R0, 3\nLW R2, 0(R1)\nHALT")
    assert r["status"] == "fault" and "aligned" in r["fault"]


def test_max_cycles_guard_on_infinite_loop():
    r = simulate("loop:\nBEQ R0, R0, loop", max_cycles=50)
    assert r["status"] == "max_cycles" and r["metrics"]["cycles"] == 50


def test_deterministic():
    p = SAMPLE_WORKLOADS["loop_sum"]["program"]
    assert simulate(p) == simulate(p)


def test_bad_initial_register_rejected():
    with pytest.raises(SimulationInputError):
        simulate("HALT", initial_registers={0: 5})
