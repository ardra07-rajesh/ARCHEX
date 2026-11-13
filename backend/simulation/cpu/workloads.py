SAMPLE_WORKLOADS = {
    "straight_line": {
        "title": "Straight-line arithmetic",
        "description": "Independent instructions: shows the ideal pipeline fill (N + 4 cycles).",
        "program": "ADDI R1, R0, 5\nADDI R2, R0, 7\nADD R3, R1, R2\nSUB R4, R2, R1\nHALT",
    },
    "raw_chain": {
        "title": "RAW data-hazard chain",
        "description": "Each instruction depends on the previous result. Toggle forwarding to compare stalls.",
        "program": "ADDI R1, R0, 3\nADD R2, R1, R1\nADD R3, R2, R1\nADD R4, R3, R2\nHALT",
    },
    "load_use": {
        "title": "Load-use hazard",
        "description": "A load followed by its consumer costs one stall cycle even with forwarding.",
        "program": "ADDI R1, R0, 42\nSW R1, 0(R0)\nLW R2, 0(R0)\nADD R3, R2, R2\nHALT",
    },
    "loop_sum": {
        "title": "Loop: sum 1..5 (control hazards)",
        "description": "A taken BNE flushes two wrong-path instructions each iteration (predict-not-taken).",
        "program": "    ADDI R1, R0, 5\n    ADDI R2, R0, 0\nloop:\n    ADD R2, R2, R1\n    ADDI R1, R1, -1\n    BNE R1, R0, loop\n    HALT",
    },
    "mem_traffic": {
        "title": "Memory traffic",
        "description": "Three stores then three loads and a combine, to exercise the memory port.",
        "program": ("ADDI R1, R0, 11\nADDI R2, R0, 22\nADDI R3, R0, 33\nSW R1, 0(R0)\nSW R2, 4(R0)\nSW R3, 8(R0)\n"
                    "LW R4, 0(R0)\nLW R5, 4(R0)\nLW R6, 8(R0)\nADD R7, R4, R5\nHALT"),
    },
}
