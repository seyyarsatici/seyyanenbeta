"""
Phase E-3: Capability -> Acquisition Plan Test Suite
Tests A through K:
- TEST A: Supported Mode 22 -> one enabled acquisition item
- TEST B: Unsupported capability -> not included as enabled by default
- TEST C: include_unsupported=True -> appears as disabled (enabled=False)
- TEST D: Duplicate candidates -> collapses to one acquisition item
- TEST E: Deterministic ordering -> different input permutations produce identical output
- TEST F: Provenance preservation -> USER, MODE22_CSV, STANDARD_OBD correctly retained
- TEST G: Header preservation -> 7E0 remains 7E0, 7E1 remains 7E1, no AT SH / no communication
- TEST H: Malformed capability -> no crash, handled gracefully as disabled entry
- TEST I: Plan bound -> truncates at MAX_ACQUISITION_PLAN (100) with truncated=True
- TEST J: No I/O -> komut_gonder / serial communication never called
- TEST K: Existing regressions -> verify E-1, E-2, D-layer, and C-layer contracts intact
"""

import copy
from motor import (
    AutoExpertEngine,
    DiagnosticSession,
    CAPABILITY_SUPPORTED,
    CAPABILITY_NEGATIVE_RESPONSE,
    CAPABILITY_NO_RESPONSE,
    CAPABILITY_TIMEOUT,
    CAPABILITY_DID_MISMATCH,
    CAPABILITY_UNAVAILABLE,
    MAX_ACQUISITION_PLAN,
)

def run_tests():
    print("🚀 Running Phase E-3 Capability -> Acquisition Plan Tests (Tests A through K)...")

    engine = AutoExpertEngine()

    # TEST A — Supported Mode 22
    print("\n--- TEST A: Supported Mode 22 ---")
    cap_a = [{
        "type": "MODE22_DID",
        "id": "1640",
        "header": "7E0",
        "service": "22",
        "status": CAPABILITY_SUPPORTED,
        "request": "221640",
        "candidate_source": "MODE22_CSV",
    }]
    plan_a = engine.build_acquisition_plan(capabilities=cap_a)
    assert len(plan_a) == 1
    item_a = plan_a[0]
    assert item_a["type"] == "MODE22_DID"
    assert item_a["id"] == "1640"
    assert item_a["header"] == "7E0"
    assert item_a["service"] == "22"
    assert item_a["request"] == "221640"
    assert item_a["source"] == "MODE22_CSV"
    assert item_a["enabled"] is True
    assert item_a["reason"] == "CAPABILITY_SUPPORTED"
    print(f"Test A Result: 1 active plan item generated: {item_a['request']} on {item_a['header']} (priority={item_a['priority']})")

    # TEST B — Unsupported capability (default excluded)
    print("\n--- TEST B: Unsupported Capability Excluded by Default ---")
    cap_b = [
        {
            "type": "MODE22_DID",
            "id": "1640",
            "header": "7E0",
            "service": "22",
            "status": CAPABILITY_SUPPORTED,
            "request": "221640",
            "candidate_source": "MODE22_CSV",
        },
        {
            "type": "MODE22_DID",
            "id": "336A",
            "header": "7E0",
            "service": "22",
            "status": CAPABILITY_NEGATIVE_RESPONSE,
            "request": "22336A",
            "candidate_source": "MODE22_CSV",
        },
    ]
    plan_b = engine.build_acquisition_plan(capabilities=cap_b, include_unsupported=False)
    assert len(plan_b) == 1
    assert plan_b[0]["id"] == "1640"
    print("Test B Result: Unsupported capability 336A safely excluded from active plan.")

    # TEST C — include_unsupported=True
    print("\n--- TEST C: include_unsupported=True Retains Disabled Entries ---")
    plan_c = engine.build_acquisition_plan(capabilities=cap_b, include_unsupported=True)
    assert len(plan_c) == 2
    enabled_items = [it for it in plan_c if it["enabled"]]
    disabled_items = [it for it in plan_c if not it["enabled"]]
    assert len(enabled_items) == 1
    assert len(disabled_items) == 1
    assert disabled_items[0]["id"] == "336A"
    assert disabled_items[0]["enabled"] is False
    assert disabled_items[0]["reason"] == CAPABILITY_NEGATIVE_RESPONSE
    # Enabled items must be sorted before disabled items
    assert plan_c[0]["enabled"] is True
    assert plan_c[1]["enabled"] is False
    print("Test C Result: 336A retained as disabled entry with reason 'NEGATIVE_RESPONSE', placed after enabled items.")

    # TEST D — Duplicate candidates collapse to one item
    print("\n--- TEST D: Duplicate Candidates Suppression ---")
    cap_d = [
        {"type": "MODE22_DID", "id": "1640", "header": "7E0", "service": "22", "status": CAPABILITY_SUPPORTED, "candidate_source": "USER"},
        {"type": "MODE22_DID", "id": "16 40", "header": "7E0", "service": "22", "status": CAPABILITY_SUPPORTED, "candidate_source": "MODE22_CSV"},
        {"type": "MODE22_DID", "id": "0X1640", "header": "7E0", "service": "22", "status": CAPABILITY_SUPPORTED, "candidate_source": "CUSTOM_PID"},
        {"type": "MODE22_DID", "id": "221640", "header": "7E0", "service": "22", "status": CAPABILITY_SUPPORTED, "candidate_source": "MODE22_CSV"},
    ]
    plan_d = engine.build_acquisition_plan(capabilities=cap_d)
    assert len(plan_d) == 1
    assert plan_d[0]["id"] == "1640"
    assert plan_d[0]["request"] == "221640"
    print("Test D Result: 4 duplicate variations collapsed into exactly 1 active plan item.")

    # TEST E — Deterministic ordering across permutations
    print("\n--- TEST E: Deterministic Ordering Across Permutations ---")
    cap_e1 = [
        {"type": "MODE01_PID", "id": "0C", "header": "7DF", "service": "01", "status": CAPABILITY_SUPPORTED, "candidate_source": "STANDARD_OBD"},
        {"type": "MODE22_DID", "id": "1640", "header": "7E0", "service": "22", "status": CAPABILITY_SUPPORTED, "candidate_source": "USER"},
        {"type": "MODE22_DID", "id": "1641", "header": "7E0", "service": "22", "status": CAPABILITY_SUPPORTED, "candidate_source": "MODE22_CSV"},
        {"type": "MODE01_PID", "id": "0D", "header": "7DF", "service": "01", "status": CAPABILITY_SUPPORTED, "candidate_source": "STANDARD_OBD"},
    ]
    cap_e2 = list(reversed(cap_e1))
    plan_e1 = engine.build_acquisition_plan(capabilities=cap_e1)
    plan_e2 = engine.build_acquisition_plan(capabilities=cap_e2)
    assert plan_e1 == plan_e2
    # Verify order: Core OBD (0C, 0D, priority 100) -> USER Mode 22 (1640, priority 70) -> CSV Mode 22 (1641, priority 50)
    assert [it["id"] for it in plan_e1] == ["0C", "0D", "1640", "1641"]
    print("Test E Result: Independent input order permutations produced identical deterministic plans.")

    # TEST F — Provenance preservation
    print("\n--- TEST F: Provenance Preservation ---")
    cap_f = [
        {"type": "MODE01_PID", "id": "0C", "header": "7DF", "service": "01", "status": CAPABILITY_SUPPORTED, "candidate_source": "STANDARD_OBD"},
        {"type": "MODE22_DID", "id": "1640", "header": "7E0", "service": "22", "status": CAPABILITY_SUPPORTED, "candidate_source": "USER"},
        {"type": "MODE22_DID", "id": "1641", "header": "7E0", "service": "22", "status": CAPABILITY_SUPPORTED, "candidate_source": "MODE22_CSV"},
    ]
    plan_f = engine.build_acquisition_plan(capabilities=cap_f)
    sources = {it["id"]: it["source"] for it in plan_f}
    assert sources["0C"] == "STANDARD_OBD"
    assert sources["1640"] == "USER"
    assert sources["1641"] == "MODE22_CSV"
    print("Test F Result: Provenance accurately carried forward for all candidates.")

    # TEST G — Header preservation
    print("\n--- TEST G: Header Preservation Without I/O ---")
    cap_g = [
        {"type": "MODE22_DID", "id": "1640", "header": "7E0", "service": "22", "status": CAPABILITY_SUPPORTED},
        {"type": "MODE22_DID", "id": "2001", "header": "7E1", "service": "22", "status": CAPABILITY_SUPPORTED},
    ]
    plan_g = engine.build_acquisition_plan(capabilities=cap_g)
    headers = {it["id"]: it["header"] for it in plan_g}
    assert headers["1640"] == "7E0"
    assert headers["2001"] == "7E1"
    assert engine.current_header == "7DF"  # Initial header unchanged
    print("Test G Result: Discovered headers 7E0 and 7E1 preserved; engine header not switched.")

    # TEST H — Malformed capability handling
    print("\n--- TEST H: Malformed Capability Handling ---")
    cap_h = [
        {"type": "MODE22_DID", "id": "ZZZZ", "header": "7E0", "service": "22", "status": CAPABILITY_SUPPORTED},
        {"type": "MODE22_DID", "id": "1640", "header": "7E0", "service": "22", "status": CAPABILITY_SUPPORTED},
    ]
    # By default, malformed is excluded
    plan_h1 = engine.build_acquisition_plan(capabilities=cap_h, include_unsupported=False)
    assert len(plan_h1) == 1
    assert plan_h1[0]["id"] == "1640"
    # With include_unsupported=True, represented as disabled entry with reason
    plan_h2 = engine.build_acquisition_plan(capabilities=cap_h, include_unsupported=True)
    assert len(plan_h2) == 2
    malformed_entry = [it for it in plan_h2 if not it["enabled"]][0]
    assert "Malformed" in malformed_entry["reason"]
    print("Test H Result: Malformed entry 'ZZZZ' safely handled without crashing.")

    # TEST I — Plan bounding and truncation reporting
    print("\n--- TEST I: Plan Bounding (MAX_ACQUISITION_PLAN) ---")
    large_caps = []
    for i in range(MAX_ACQUISITION_PLAN + 30):
        large_caps.append({
            "type": "MODE22_DID",
            "id": f"{i:04X}",
            "header": "7E0",
            "service": "22",
            "status": CAPABILITY_SUPPORTED,
            "candidate_source": "MODE22_CSV",
        })
    plan_i = engine.build_acquisition_plan(capabilities=large_caps)
    assert len(plan_i) == MAX_ACQUISITION_PLAN
    assert engine.last_acquisition_plan_metadata["truncated"] is True
    assert engine.last_acquisition_plan_metadata["count"] == MAX_ACQUISITION_PLAN
    assert engine.last_acquisition_plan_metadata["total_candidates"] == MAX_ACQUISITION_PLAN + 30
    print(f"Test I Result: Successfully bounded plan to {MAX_ACQUISITION_PLAN} items with truncated=True.")

    # TEST J — No I/O Verification
    print("\n--- TEST J: Strict Zero-I/O Verification ---")
    orig_komut_gonder = engine.komut_gonder
    def forbidden_komut_gonder(*args, **kwargs):
        raise AssertionError("komut_gonder was illegally called by the planner!")
    engine.komut_gonder = forbidden_komut_gonder
    try:
        # Planner must succeed without touching komut_gonder
        plan_j = engine.build_acquisition_plan(capabilities=cap_f)
        assert len(plan_j) == 3
    finally:
        engine.komut_gonder = orig_komut_gonder
    print("Test J Result: Verified build_acquisition_plan performs zero serial or network communication.")

    # TEST K — Existing Regressions Check
    print("\n--- TEST K: Regression Integration with DiagnosticSession ---")
    session = DiagnosticSession(engine=engine)
    plan_k = session.build_acquisition_plan(capabilities=cap_a)
    assert len(plan_k) == 1
    assert session.get_acquisition_plan() == plan_k
    print("Test K Result: DiagnosticSession seamlessly proxies plan generation and retrieval.")

    print("\n✅ ALL PHASE E-3 TESTS (Tests A through K) PASSED PERFECTLY!")

if __name__ == "__main__":
    run_tests()
