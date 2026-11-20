# Phase I-5 Walkthrough: Advanced Reasoning Layer

## 1. Executive Summary
Phase I-5 completes the **Knowledge & Intelligence Layer (Phase I)** of the Seyyanen automotive diagnostic platform. It establishes a structured, deterministic, bounded diagnostic reasoning process that synthesizes:
- **Validated Evidence & Telemetry** (from Phase C Data Trust, Phase D Evidence Engine, and Phase G Advanced Diagnostics)
- **Vehicle / ECU Specific Context** (from Phase I-2 Vehicle/ECU Knowledge profiles)
- **Empirical Failure Patterns** (from Phase I-3 Failure Pattern Library)
- **Historical Diagnostic Cases** (from Phase I-4 Historical Case Analysis)
- **Hypothesis Competition & Test Results** (from Phase D-2, Phase H-1/H-2/H-3 Guided Sequencing, and Phase H-4 Root Cause Analysis)
- **Explicit Contradictions & Negative Evidence**
- **Causal Assessment** (Rigorous enforcement that `Correlation != Causation`, isolating communication artifacts)
- **Knowledge Provenance & Deterministic Audit Traces**

Seyyanen strictly prevents diagnostic reductionism:
- **Never** converts `DTC → part`
- **Never** assumes `similar case → same repair`
- **Never** claims `pattern → guaranteed root cause`
- **Never** confuses `correlation with causation`
- **Never** equates `communication failure with component failure`
- **Never** emits unconditional autonomous repair commands (`replace component X` is strictly prohibited)

---

## 2. Architecture & Reasoning Chain

The Seyyanen reasoning chain enforces:
```
data
→ validation (Phase C)
→ evidence (Phase D)
→ pattern matching (Phase I-3)
→ hypothesis generation (Phase D/G/I)
→ competing hypotheses (Phase I-5)
→ distinguishing test selection (Phase H-3)
→ safe test execution (Phase H-1 / H-2)
→ test result evaluation
→ causal assessment (Phase H-4 / I-5)
→ historical / contextual evidence (Phase I-2 / I-4)
→ deterministic ranked conclusion
→ verification
```

### Architectural Boundaries
- **I-5 is purely an analytical reasoning layer**. It consumes evidence and emits structured, bounded reasoning objects.
- **Zero transport access**: I-5 never opens sockets, communicates with ELM/CAN drivers, clears DTCs, or sends UDS/OBD frames.
- **Strict safety gating**: Any recommended distinguishing tests are strictly validated against `ServiceSafetyClassification.READ_ONLY`. Destructive or actuating operations (e.g. Mode 04, UDS 0x14, 0x2E, 0x27, 0x2F, 0x34, 0x36, 0x37) are strictly blocked.
- **Workflow orchestrator integration**: Recommendations are consumed by H-5 (`DiagnosticWorkflowEngine`) and executed via safe guided sequences (H-1/H-2).

---

## 3. Core Reasoning Model

The reasoning structures defined in `advanced_reasoning_layer.py`:

| Component | Responsibility |
| :--- | :--- |
| `ReasoningEvidenceContribution` | Atomic piece of evidence with source, type, summary, weight, direction (`SUPPORTS`, `CONTRADICTS`, `NEUTRAL`, `MISSING_EXPECTED`), and audit provenance. |
| `ReasoningContradiction` | Explicit clash between two sources (e.g. Current Sensor Telemetry vs Historical Case or Pattern expectation), assigning a structured penalty weight. |
| `ReasoningCandidate` | Competing diagnostic hypothesis with supporting and contradicting contributions, missing expected observations, distinguishing tests, causal role, causal basis, and explainable score decomposition. |
| `ReasoningTraceStep` | Audit step capturing execution phase, action, inputs considered, and analytical findings. |
| `DiagnosticReasoningSession` | Complete session container preserving vehicle context, operating conditions, ranked candidates, alternatives, contradictions, recommended distinguishing tests, overall explainable conclusion, calibration uncertainty, and serialization schema. |

---

## 4. Multi-Source Evidence Fusion & Contradiction Handling

The engine ingests multi-source data while preserving provenance:
1. **Current Telemetry Features**: Evaluated against expected vs contradicting thresholds.
2. **Phase I-3 Failure Patterns**: Matches contribute mechanistic evidence; conflicting features generate `ReasoningContradiction` and apply penalty weights (-0.35).
3. **Phase I-4 Historical Cases**: Highly similar confirmed cases contribute contextual weight; any conflicting feature drops historical relevance and applies severe contradiction penalties (-0.50).
4. **Phase H-1/H-2 Test Results**: Passed tests elevate causal basis to `HYPOTHESIS_TEST_SUPPORT`. Failed tests for a hypothesis generate definitive negative evidence.
5. **Phase I-1 Knowledge & Distinguishing Tests**: Domain rules and distinguishing tests attach directly to relevant candidates.

### Priority Invariant: Current Evidence Dominates
Current vehicle telemetry strictly overrides historical similarity. If an unverified historical case suggests component X, but current live telemetry shows normal operational boundaries for X, the contradiction is flagged and the candidate's score is penalized.

---

## 5. Causal Reasoning & Invariants

### 5.1 Correlation != Causation
- Candidates with purely co-occurring telemetry anomalies receive `CausalBasis.CORRELATIONAL_ONLY` and `CausalRole.CORRELATED_OBSERVATION`.
- Candidates supported by empirical failure patterns receive `CausalBasis.DIRECT_MECHANISTIC_EVIDENCE`.
- Candidates supported by executed, passed physical tests receive `CausalBasis.HYPOTHESIS_TEST_SUPPORT`.
- Candidates confirmed by physical test plus technician outcome receive `CausalBasis.CONFIRMED` and `CausalRole.PRIMARY_ROOT_CAUSE`.

### 5.2 Communication Failure Isolation
- **Invariant**: `communication failure != component failure`.
- Telemetry showing U-codes (e.g., `U0101`) or bus communication timeouts is assigned `CausalRole.COMMUNICATION_ARTIFACT` and documented as a bus/communication anomaly, preventing misclassification as internal hardware component failure.

---

## 6. Deterministic, Explainable Ranking

Ranking is strictly deterministic and fully decomposable:
$$\text{Raw Score} = (\text{Base Evidence} \times 0.50) + (\text{Applicability Weight} \times 0.10) + (\text{Historical Relevance} \times 0.15) + \text{Causal Boost}$$
$$\text{Final Score} = \max(0.0, \min(1.0, \text{Raw Score} - \text{Contradiction Penalty}))$$

- Tie-breaking is deterministic (sorted by `(-overall_score, candidate_id)`).
- Every candidate maintains an `explanations` breakdown logging positive evidence, historical relevance, causal basis, and applied penalties.

---

## 7. Uncertainty & Distinguishing Tests

### 7.1 Uncertainty Calibration
- `HIGH_CONFIDENCE`: Score $\ge 0.75$ and zero active contradictions.
- `MODERATE_CONFIDENCE`: Score $\ge 0.45$ and zero active contradictions.
- `LOW_CONFIDENCE`: Score $< 0.45$.
- `CONTRADICTORY`: One or more active contradictions detected.
- `INSUFFICIENT_EVIDENCE`: No positive evidence found or active inputs insufficient to distinguish candidates.

### 7.2 Distinguishing Test Selection (H-3 Integration)
When competing candidates remain close in confidence or evidence is inconclusive, the engine recommends up to $N$ non-destructive distinguishing tests (filtered via `ServiceSafetyClassification.READ_ONLY`), advising the technician:
`"Current evidence most strongly supports hypothesis X; verify using test Y."`

---

## 8. Integration Adapters

- **`ReasoningWorkflowAdapter`**: Integrates I-5 into Phase H-5 (`DiagnosticWorkflowEngine`), providing:
  - `to_workflow_step_suggestion()`: Formats recommended distinguishing tests into safe H-5 steps.
  - `to_technician_summary()`: Generates an executive diagnostic brief for workshop technicians.
- **`DiagnosticGraphReasoningIntegrator`**: Integrates I-5 sessions into Phase G-5 (`DiagnosticGraph`):
  - Adds reasoning candidate nodes and edge connections with strict boundary enforcement: `GraphEdgeType.EVIDENCE_FOR` and `GraphEdgeType.CONTRADICTS`.
  - Invariant enforced: `RELATIONSHIP != CAUSALITY`. Causal edges are never created without explicit test confirmation.

---

## 9. Realistic Synthetic Diagnostic Scenario

A complete, synthetic scenario was executed and verified:
- **Vehicle Context**: Chevrolet Aveo 2012, 1.3L CDTI (LDV), E87 ECU.
- **Observations**: Lean mixture deviation (`LTFT = +24.8%`), command/response lag (`COMMAND_LAG_MS = 210.0`).
- **Telemetry**: Active `P0171`.
- **Competing Hypotheses**:
  - Candidate A: Intake Air Leak / Vacuum Compromise.
  - Candidate B: MAF Sensor Calibration Drift.
  - Candidate C: Fuel Pump Delivery Pressure Deficit.
  - Candidate D: Normal Transient Variation.
- **Reasoning Execution**:
  1. I-3 matched `PAT_VACUUM_LEAK` (grade HIGH).
  2. I-4 retrieved confirmed case `CASE_AVEO_PCV_001` (relevance 0.82) and contradictory case `CASE_MAF_002` (penalized).
  3. Step 8 ranked Candidate A as top candidate (Score $> 0.70$).
  4. Step 9 recommended safe smoke test `TEST_SMOKE_PCV` as the primary distinguishing test.
  5. Overall conclusion cleanly advised test verification without autonomous repair command.

---

## 10. Test & Regression Results

### 10.1 Dedicated I-5 Test Suite (`test_phase_i5.py`)
All 21 comprehensive test methods passed in 0.003s:
1. `test_01_reasoning_session_lifecycle`: Verified session creation, UUID stability, and vehicle context ingestion.
2. `test_02_evidence_ingestion_and_provenance`: Ingested validated features preserving origin, quality, and direction.
3. `test_03_hypothesis_competition_and_deduplication`: Verified multi-candidate evaluation without premature winner forcing.
4. `test_04_deterministic_ranking_and_explainability`: Confirmed deterministic tie-breaking and explainable score decomposition.
5. `test_05_vehicle_and_ecu_specificity`: Higher applicability boost applied to matching engine/ECU families.
6. `test_06_failure_pattern_integration`: Pattern match translated to mechanistic evidence without direct root-cause assumption.
7. `test_07_historical_case_integration`: Confirmed historical cases contribute contextual evidence.
8. `test_08_current_evidence_overrides_historical_conflict`: Current contradictory evidence penalized historical case score.
9. `test_09_communication_failure_safeguard`: U-codes and bus timeouts classified as `COMMUNICATION_ARTIFACT`.
10. `test_10_multi_ecu_reasoning`: ECU context isolation maintained between ECM and TCM.
11. `test_11_causal_reasoning_correlation_vs_causation`: Purely correlated candidates restricted to `CORRELATIONAL_ONLY`.
12. `test_12_test_supported_causality`: Passed distinguishing test elevated candidate to `HYPOTHESIS_TEST_SUPPORT`.
13. `test_13_insufficient_evidence_conclusion`: Empty inputs safely yield `INSUFFICIENT_EVIDENCE` outcome.
14. `test_14_distinguishing_test_recommendation`: Safe read-only tests recommended to distinguish competitors.
15. `test_15_workflow_adapter_technician_summary`: Concise summary formatted for H-5 consumption.
16. `test_16_diagnostic_graph_reasoning_integration`: Safe graph edge integration preserving `RELATIONSHIP != CAUSALITY`.
17. `test_17_reasoning_trace_and_determinism`: Deterministic 10-step execution trace verified across runs.
18. `test_18_serialization_round_trip`: Lossless JSON serialization/deserialization validated.
19. `test_19_safety_boundary_and_no_autonomous_repair`: Rejection of destructive tests and no autonomous "replace part" command.
20. `test_20_large_evidence_set_performance_benchmark`: 100+ telemetry features evaluated in < 15ms.
21. `test_21_realistic_end_to_end_diagnostic_scenario`: End-to-end synthetic scenario verified.

### 10.2 Full Platform Regression Matrix
Executed command:
```powershell
python -m unittest test_phase_i5.py test_phase_i4.py test_phase_i3.py test_phase_i2.py test_phase_i1.py test_phase_h_final.py test_phase_h5.py test_phase_h4.py test_phase_h3.py test_phase_h2.py test_phase_h1.py test_phase_g_final.py test_phase_g5.py test_phase_g4.py test_phase_f7.py test_vin_parser.py test_reset.py
```
**Result**: `Ran 405 tests in 32.429s. OK.`
- 0 Failures, 0 Errors across all phases (C, D, E, F, G, H, I).

---

## 11. Boundedness, Safety & Non-Goals

- **Bounded Execution**: Candidate evaluation is capped at `max_candidates` (default 10); distinguishing tests capped at `max_distinguishing_tests` (default 3); trace steps bounded; graph edge insertion bounded.
- **Safety**: Purely read-only; no transport handle access; no actuator triggering.
- **Non-Goals strictly adhered to**:
  - No Phase J features implemented.
  - No database or cloud synchronization added.
  - No machine-learning training pipelines or LLM chatbot agents introduced.

---

I-5 PASS — READY FOR I-FINAL
