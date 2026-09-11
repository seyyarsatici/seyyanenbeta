# Phase H-1: Guided Diagnostic Procedures Foundation — Walkthrough & Final Report

## Executive Summary
Phase **H-1 — Guided Diagnostic Procedures Foundation** introduces the procedure-planning and guided-decision layer to the Seyyanen automotive diagnostic platform.

H-1 bridges the evidence, anomaly, hypothesis, and graph layers from Phase G into an actionable, deterministic, technician-guided diagnostic procedure:
> **"Given the current vehicle context, ECU state, DTCs, anomalies, evidence, hypotheses, operating conditions, and diagnostic graph, what should the technician check next, and why?"**

All **24 Phase H-1 acceptance scenarios (A through X)** and the complete regression matrix across Phases G, F, D, and C (over 200 scenarios) have executed and passed with 100% compliance.

---

## 1. Files Created & Modified

| File | Status | Description |
|---|---|---|
| [`guided_procedures.py`](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/guided_procedures.py) | **CREATED** | Core Phase H-1 module implementing procedure data models, deterministic prioritizer, branching logic, safety guardrails, state machine, and engine. |
| [`test_phase_h1.py`](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/test_phase_h1.py) | **CREATED** | Comprehensive dedicated test suite covering all 24 required scenarios (A through X). |
| [`h1_walkthrough.md`](file:///c:/Users/chnyg/OneDrive/Belgeler/py/seyyanen/h1_walkthrough.md) | **CREATED** | Final Phase H-1 walkthrough, architecture documentation, and acceptance report. |

---

## 2. Architectural Role & Invariants

H-1 sits directly after the Phase G diagnostic evidence and graph layer:
```
Vehicle + ECU Context
  → Acquisition (G-1 / G-2 / G-4)
    → Validation (C / D / E / F)
      → Advanced Fault Analysis (G-3)
        → Vehicle-Wide Diagnostic Graph (G-5)
          → Guided Diagnostic Procedures (H-1)
```

### Core Invariants Enforced:
1. **Guided, Not Autonomous**: The engine recommends and sequences diagnostic steps with explainable rationale, but **NEVER** autonomously executes destructive tests, actuator tests, programming, coding, ECU writes, or unsafe bus operations.
2. **Execution Modes Restricted in H-1**:
   - `INFORMATIONAL`: Review existing evidence, DTCs, graph relationships.
   - `OBSERVATIONAL`: Inspect live telemetry, operating conditions, visual checks.
   - `MEASUREMENT`: Instruct technician to measure physical quantities with meters/tools.
   - `ACTIVE_DIAGNOSTIC`: Represented in data models for future readiness, but strictly **BLOCKED / NON-EXECUTABLE** in H-1.
3. **Strict Safety Invariant Reuse**: Mode 04/14 DTC clear, 0x2E (Write), 0x27 (Security Access), 0x2F (Actuation/Bi-directional control), and 0x34/36/37 (Programming) are strictly rejected before execution.
4. **Deterministic & Offline**: 100% deterministic step prioritization, scoring, and branching without cloud or LLM dependencies.
5. **Communication Fault Separation**: Unreachable ECUs produce communication/power/ground investigation procedures, strictly avoiding false component replacement recommendations.
6. **Zero Workshop Fabrication**: Never invents unverified pinouts, exact voltages, or torque specs; instructs the technician to inspect physical components according to the approved workshop procedure.

---

## 3. Public APIs & Data Models

### A. Enumerations
- **`ProcedureState`**: `DRAFT`, `READY`, `ACTIVE`, `WAITING_FOR_INPUT`, `BLOCKED`, `COMPLETED`, `FAILED`, `ABORTED`.
- **`StepExecutionMode`**: `INFORMATIONAL`, `OBSERVATIONAL`, `MEASUREMENT`, `ACTIVE_DIAGNOSTIC`.
- **`StepPriority`**: `MANDATORY`, `RECOMMENDED`, `OPTIONAL`, `INFORMATIONAL`.
- **`ObservationResultType`**: `NORMAL`, `ABNORMAL`, `NOT_PRESENT`, `INTERMITTENT`, `UNKNOWN`, `NOT_TESTED`, `MEASURED_VALUE`, `COMMUNICATION_FAILURE`.
- **`ProcedureOutcome`**: `HYPOTHESIS_SUPPORTED`, `HYPOTHESIS_WEAKENED`, `HYPOTHESES_DISCRIMINATED`, `INSUFFICIENT_EVIDENCE`, `COMMUNICATION_PROBLEM`, `NO_CONFIDENT_CONCLUSION`, `REQUIRES_MANUAL_TEST`, `SAFETY_BLOCKED`.
- **`StopConditionType`**: `HYPOTHESIS_RESOLVED`, `ALL_STEPS_COMPLETED`, `SAFETY_RESTRICTION`, `COMMUNICATION_FAULT`, `DATA_INSUFFICIENT`, `MANUAL_INTERVENTION_REQUIRED`, `PREREQUISITE_FAILED`, `VEHICLE_MISMATCH`.

### B. Core Data Structures
- **`DiagnosticProcedure`**: Root serializable container managing procedure lifecycle, ordered steps, state transitions, provenance, stop conditions, and final outcome.
- **`DiagnosticStep`**: Structured unit of diagnostic guidance containing `step_id`, `sequence`, `title`, `technician_instruction`, `purpose`, `rationale`, `target_ecu`, `preconditions`, `expected_observation`, `possible_outcomes`, `branches`, `priority`, `execution_mode`, `safety_classification`, `provenance`, `confidence`, and `technician_observation`.
- **`DiagnosticBranch`**: Conditional transition linking an observation outcome to a target `step_id` or terminal `ProcedureOutcome`.
- **`DiagnosticPrecondition`**: Prerequisites required before performing a step (operating condition, ECU state, required signals).
- **`DiagnosticExpectedObservation`**: Concrete expected observations, signal bounds, or physical relationships.
- **`DiagnosticStopCondition`**: Explicit termination rules ensuring safe and bounded procedure completion.
- **`TechnicianObservation`**: Structured feedback recorded by the technician (`result_type`, `measured_value`, `unit`, `notes`, `technician_id`, `timestamp`).
- **`DiagnosticProcedureContext`**: Vehicle metadata, ECU inventory, transport health, and operating condition context.

### C. Engine Class: `GuidedProcedureEngine`
- `generate_procedure(...)`: Ingests G-3 hypotheses, DTCs, anomalies, G-4 multi-ECU scans, and G-5 graphs to create a deterministic `DiagnosticProcedure`.
- `record_step_observation(...)`: Records a technician observation on the active step, evaluates conditional branches, adjusts confidence, advances step or terminates procedure.
- `validate_safety(...)`: Audits any step against prohibited services and blocked execution modes.

---

## 4. Deterministic Prioritization & Information Gain

Step sequencing is governed by `StepPrioritizer` using an explainable, deterministic scoring formula:
$$\text{Score} = w_{\text{disc}} \cdot S_{\text{disc}} + w_{\text{conf}} \cdot S_{\text{conf}} + w_{\text{safe}} \cdot S_{\text{safe}} + w_{\text{cost}} \cdot S_{\text{cost}} + w_{\text{prereq}} \cdot S_{\text{prereq}}$$

Where:
- **$S_{\text{disc}}$ (Information Gain / Discrimination)**: $1.0$ if the step discriminates between 2 or more competing hypotheses (e.g. MAF sensor bias vs. Intake vacuum leak), $0.75$ for single hypothesis test, $0.4$ for general check.
- **$S_{\text{conf}}$ (Confidence)**: Inherited from G-3 evidence score and confidence calibration.
- **$S_{\text{safe}}$ (Safety)**: $1.0$ for non-destructive read-only checks; $0.0$ for blocked actions.
- **$S_{\text{cost}}$ (Cost / Duration)**: Higher score for shorter duration tests: $\max(0.1, 1.0 - \text{minutes} / 30.0)$.
- **$S_{\text{prereq}}$ (Prerequisite Readiness)**: $1.0$ if all prerequisite signals are currently present; $0.0$ if target ECU is unreachable.

Every step stores `priority_score` and a human-readable `priority_reason` explaining why it was sequenced.

---

## 5. State Machine & Lifecycle

The procedure follows a strict state machine:
- `DRAFT` $\to$ `READY`, `ABORTED`
- `READY` $\to$ `ACTIVE`, `BLOCKED`, `ABORTED`
- `ACTIVE` $\to$ `WAITING_FOR_INPUT`, `BLOCKED`, `COMPLETED`, `FAILED`, `ABORTED`
- `WAITING_FOR_INPUT` $\to$ `ACTIVE`, `BLOCKED`, `COMPLETED`, `FAILED`, `ABORTED`
- Terminal States: `COMPLETED`, `FAILED`, `ABORTED`, `BLOCKED`

Invalid transitions (e.g., `READY` directly to `COMPLETED` without activation, or transitioning out of a terminal state) are rejected with `ProcedureStateError`.

---

## 6. Test Suite Execution Summary

### A. Dedicated Phase H-1 Suite (`test_phase_h1.py`)
Command: `python -m unittest test_phase_h1.py`  
**Result: 24 / 24 Tests PASSED (100%) in 0.006s**

| Scenario | Focus Area | Status |
|---|---|---|
| `test_scenario_a_procedure_from_g3_hypothesis` | Procedure creation from G-3 hypothesis | **PASSED** |
| `test_scenario_b_procedure_from_dtc_evidence` | Procedure creation from DTC evidence | **PASSED** |
| `test_scenario_c_dtc_free_anomaly_procedure` | DTC-free anomaly procedure | **PASSED** |
| `test_scenario_d_multiple_competing_hypotheses` | Multiple competing hypotheses representation | **PASSED** |
| `test_scenario_e_deterministic_step_prioritization` | Deterministic step prioritization and explainability | **PASSED** |
| `test_scenario_f_branch_selection` | Branch selection based on technician observation | **PASSED** |
| `test_scenario_g_stop_conditions` | Stop conditions and safe termination | **PASSED** |
| `test_scenario_h_technician_observation_recording` | Technician observation recording with structured data | **PASSED** |
| `test_scenario_i_missing_data_handling` | Missing data handling and data-insufficient flagging | **PASSED** |
| `test_scenario_j_multi_ecu_procedure` | Multi-ECU procedure preserving distinct ECU identities | **PASSED** |
| `test_scenario_k_communication_failure_branching` | Communication failure branching without false replacement | **PASSED** |
| `test_scenario_l_graph_aware_evidence_references` | Graph-aware evidence references (nodes/edges) | **PASSED** |
| `test_scenario_m_provenance_preservation` | Provenance preservation across procedure and steps | **PASSED** |
| `test_scenario_n_serialization_roundtrip` | Serialization round-trip (`to_dict` / `from_dict`) | **PASSED** |
| `test_scenario_o_invalid_state_transitions` | Invalid state transitions properly rejected | **PASSED** |
| `test_scenario_p_safety_classification` | Safety classification verification on all steps | **PASSED** |
| `test_scenario_q_destructive_action_rejection` | Destructive actions (Mode 04/14, 0x2E, etc.) strictly rejected | **PASSED** |
| `test_scenario_r_actuator_execution_blocked` | Actuator and active tests blocked in H-1 | **PASSED** |
| `test_scenario_s_unsupported_workshop_data_not_invented` | Unsupported workshop pinouts/voltages not invented | **PASSED** |
| `test_scenario_t_deterministic_repeated_generation` | Identical inputs produce identical procedures | **PASSED** |
| `test_scenario_u_large_evidence_set_bounded_procedure` | Bounded procedure generation on large evidence sets | **PASSED** |
| `test_scenario_v_contradictory_evidence` | Contradictory evidence procedure handling | **PASSED** |
| `test_scenario_w_dtc_free_investigation` | Full DTC-free investigation workflow | **PASSED** |
| `test_scenario_x_alternative_hypothesis_discrimination` | Alternative hypothesis discrimination step evaluation | **PASSED** |

---

## 7. Full Regression Matrix Across Repository

| Test Suite | Command | Result | Notes |
|---|---|---|---|
| **Phase H-1** | `python -m unittest test_phase_h1.py` | **PASSED** | 24 / 24 Scenarios A–X passed (0.006s) |
| **Phase G-Final** | `python -m unittest test_phase_g_final.py` | **PASSED** | 11 / 11 Integration scenarios passed (0.009s) |
| **Phase G-5** | `python test_phase_g5.py` | **PASSED** | 41 / 41 Graph tests passed (0.016s) |
| **Phase G-4** | `python test_phase_g4.py` | **PASSED** | 38 / 38 Multi-ECU tests passed (33.267s) |
| **Phase G-3** | `python test_phase_g3.py` | **PASSED** | 24 Scenarios A–X + 100k Benchmark passed (0.530s) |
| **Phase G-2** | `python test_phase_g2.py` | **PASSED** | 46 Scenarios A–AT passed (21.320s) |
| **Phase G-1** | `python test_phase_g1.py` | **PASSED** | 7 Suites / 20 Scenarios A–T passed (43.150s) |
| **Phase F-7** | `python test_phase_f7.py` | **PASSED** | 11 Release gate tests passed (9.240s) |
| **Phase D** | `python test_d_layer_hardening.py` | **PASSED** | 8 Tests A–H passed (0.005s) |
| **Phase C** | `python test_c_layer_integration.py` | **PASSED** | Layered integration matrix passed (0.004s) |

**Total Scenarios Executed Across Entire Platform:** 200+ | **Failures:** 0

---

## 8. Known Non-Blocking Limitations & Explicit Future Scope Boundaries

### Known Non-Blocking Limitations in H-1:
1. **No Automated Physical Testing**: H-1 guides the technician to perform observational and physical checks, but does not perform automated physical multimeter measurements.
2. **Simplified Cost/Time Model**: Step duration is estimated based on general test categories (observational = 5 min, physical = 10 min) rather than vehicle-specific book times.

### Explicit Scope Exclusions (Strict Phase Boundaries):
- **H-2 OMITTED**: Automated test sequencing and active execution loops.
- **H-3 OMITTED**: Evidence-driven automatic test execution.
- **H-4 OMITTED**: Automated root-cause analysis engines.
- **H-5 OMITTED**: Enterprise diagnostic workflow engines.
- **I OMITTED**: Machine learning ontology and fleet-wide learning.
- **J OMITTED**: Production deployment infrastructure.

---

## 9. Final Gate Verdict

**H-1 PASS — READY FOR H-2**
