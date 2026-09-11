# Phase H-4: Automated Root-Cause Analysis — Release Walkthrough

## 1. Executive Summary

Phase H-4 introduces the first deterministic automated root-cause analysis layer to the Seyyanen automotive diagnostic platform. It integrates accumulated diagnostic evidence across earlier phases:
- **G-3**: Advanced Fault Analysis (Anomalies, Hypotheses, FaultEvidence)
- **G-5**: Vehicle-Wide Diagnostic Graph (Topology, Causal & Observation Edges)
- **H-1**: Guided Diagnostic Procedures
- **H-2**: Automated Test Sequencing Engine
- **H-3**: Evidence-Driven Test Selection Engine

Phase H-4 operates strictly under the rule **CORRELATION != CAUSATION**. High causal confidence requires mechanistic evidence, repeated temporal confirmation, cross-sensor agreement, or targeted discriminating test results. DTC presence is treated as diagnostic evidence rather than proof; communication failures are explicitly isolated from physical component defects; and primary causes are distinguished from downstream cascades or contributing factors.

All safety guardrails from Phases C through G remain intact: zero actuator activations (`0x2F`), zero memory/ECU writes (`0x2E`), zero programming/coding (`0x34/36/37`), zero security access (`0x27`), and zero Mode 04/14 DTC clear operations.

**Release Gate Status**: **`H-4 PASS — READY FOR H-5`**

---

## 2. Core Architectural Role & Separation of Concerns

The diagnostic pipeline boundary is strictly preserved:
- **G-3**: Detects sensor anomalies and formulates initial fault hypotheses.
- **G-5**: Models vehicle topological relationships and diagnostic graph structures.
- **H-1**: Prepares guided step-by-step diagnostic procedures.
- **H-2**: Orchestrates and executes tests in a safe, stateful sequence.
- **H-3**: Chooses the most informative next test to reduce diagnostic uncertainty.
- **H-4 (This Phase)**: Integrates accumulated multi-source evidence to identify, rank, and explain the most likely root causes, while tracking alternatives, contradictions, and uncertainty.
- **H-5 (Excluded)**: End-to-end diagnostic workflow manager (not implemented in this phase).

---

## 3. Data Models Implemented (`automated_root_cause_analyzer.py`)

### 3.1 Enumerations
1. **`RootCauseCandidateStatus`**:
   - `POSSIBLE`, `PLAUSIBLE`, `LEADING`, `STRONGLY_SUPPORTED`, `UNRESOLVED`, `WEAKENED`, `RULED_OUT`.
2. **`CausalBasis`**:
   - `DIRECT_MECHANISTIC_EVIDENCE`
   - `REPEATED_TEMPORAL_EVIDENCE`
   - `CONTROLLED_OBSERVATIONAL_SUPPORT`
   - `CROSS_SENSOR_CONSISTENCY`
   - `CROSS_ECU_CONSISTENCY`
   - `HYPOTHESIS_TEST_SUPPORT`
   - `INDIRECT_EVIDENCE`
   - `CORRELATIONAL_ONLY`
   - `INSUFFICIENT`
3. **`CausalRole`**:
   - `PRIMARY_ROOT_CAUSE`
   - `CONTRIBUTING_FACTOR`
   - `SECONDARY_EFFECT`
   - `CORRELATED_OBSERVATION`
   - `UNRELATED_FINDING`
4. **`RootCauseCertaintyLevel`**:
   - `CONFIRMED`
   - `HIGH_CERTAINTY`
   - `MODERATE_CERTAINTY`
   - `LOW_CERTAINTY`
   - `INCONCLUSIVE`
5. **`AnalysisConclusionState`**:
   - `ROOT_CAUSE_IDENTIFIED`
   - `ROOT_CAUSE_STRONGLY_SUPPORTED`
   - `LEADING_CANDIDATE_ONLY`
   - `MULTIPLE_PLAUSIBLE_CAUSES`
   - `CONFLICTED_EVIDENCE`
   - `INSUFFICIENT_EVIDENCE`
   - `COMMUNICATION_ISSUE_UNRESOLVED`
   - `REQUIRES_MANUAL_VERIFICATION`
   - `NO_CONFIDENT_ROOT_CAUSE`
6. **`TechnicianInputStatus`**:
   - `CONFIRMED`, `REJECTED`, `NOT_CHECKED`, `UNABLE_TO_VERIFY`, `COMPONENT_REPLACED`, `OBSERVATION`.

### 3.2 Structured Classes
- **`EvidenceReference`**: Retains source, timestamp, quality, ECU, signal/PID, session, analytical method, direct/indirect flag, polarity (`SUPPORTS`/`CONTRADICTS`), and fingerprint for duplicate prevention.
- **`CandidateScoreBreakdown`**: Transparent breakdown containing `support_score`, `contradiction_score`, `coverage_score`, `quality_score`, `test_confirmation_score`, `causal_basis_score`, `consistency_score`, and `composite_score`.
- **`RootCauseCandidate`**: Full candidate structure tracking candidate ID, title, affected ECU/system, component, status, causal role, causal basis, scores, supporting/contradicting evidence and tests, cross-sensor and cross-ECU signals, operating conditions, and temporal evidence.
- **`ReasoningTraceStep`**: Traceable step capturing rule name, prerequisite satisfied, supporting/contradicting evidence matched, score impact, and rationale.
- **`RootCauseConclusion`**: Primary candidate summary, confidence, certainty level, causal basis, supporting/contradicting summaries, alternatives, unresolved uncertainties, recommended final verification, technician explanation, and machine-readable reasoning trace.
- **`RootCauseAnalysis`**: Complete session artifact with analysis ID, vehicle ID, session ID, timestamp, target ECU, primary and alternative candidates, contributing factors, ruled-out candidates, test history, unresolved questions, conclusion, safety state, version, and serialization methods (`to_dict()`, `from_dict()`).
- **`AutomatedRootCauseAnalyzer`**: The core reasoning engine with deterministic candidate ranking, rule-based inference, graph integration, and bounded execution.

---

## 4. Key Diagnostic Principles Enforced

1. **Correlation != Causation**: Candidates supported solely by correlation receive `CausalBasis.CORRELATIONAL_ONLY` and cannot achieve `HIGH_CERTAINTY` or `CONFIRMED`.
2. **DTC Semantics**: DTCs are treated as corroborating evidence, never definitive proof. DTC-free root causes are supported, and physical contradictions override DTC presence.
3. **Communication Fault Isolation**: Communication failures (timeout, unreachable ECU) are classified as `COMMUNICATION_ISSUE_UNRESOLVED` or communication anomalies, preventing false component defect conclusions.
4. **Primary vs Secondary Cascades**: Secondary effects (e.g. misfire caused by lean fuel mixture) are identified and classified into `SECONDARY_EFFECT` or `CONTRIBUTING_FACTOR` rather than independent root causes.
5. **Cross-Sensor & Cross-ECU Consistency**: Coherent multi-sensor and multi-ECU patterns elevate causal basis and consistency scores.
6. **Double-Counting Prevention**: Duplicate evidence sharing the same observation fingerprint (`{target_ecu}:{signals}:{summary}`) is deduplicated.
7. **Discriminating Test History**: Targeted test results from H-3/H-2 carrying discriminating power between competing hypotheses receive higher causal weight than generic observations.
8. **Feedback Loop with H-3/H-2**: When certainty is insufficient, H-4 generates a structured `recommended_final_verification` which can feed into H-3 for test selection and H-2 for execution without H-4 executing tests itself.
9. **Technician Input & Post-Repair Validation**: Technician inputs are recorded with provenance and cannot unilaterally overwrite physical proof. Component replacement requires post-repair verification before concluding successful resolution.
10. **Bounded Reasoning & Memory Safety**: Causal search depth, candidate count, evidence references, and reasoning steps are strictly capped to prevent graph explosion or infinite loops.

---

## 5. Verification & Acceptance Results

### 5.1 Dedicated Phase H-4 Test Suite (`test_phase_h4.py`)
All 42 scenarios (A through AP) pass cleanly:
```
Ran 42 tests in 0.009s
OK
```

| Test Group | Scenarios Tested | Status |
| :--- | :--- | :---: |
| **A – D** | Single strong candidate, competing hypotheses, DTC-supported hypothesis, DTC-free root cause | **PASS** |
| **E – G** | Contradictory evidence, low-quality evidence penalty, communication failure isolation | **PASS** |
| **H – J** | Multi-ECU root causes, primary vs contributing factor, secondary effect cascades | **PASS** |
| **K – N** | Temporal precedence, cross-sensor consistency, cross-ECU consistency, duplicate evidence prevention | **PASS** |
| **O – R** | Discriminating test result weighting, weak correlation handling, strong targeted test evidence, no-confident-root-cause outcome | **PASS** |
| **S – V** | Multiple plausible causes, H-3/H-2 feedback loop, technician confirmation, technician rejection | **PASS** |
| **W – Z** | Post-repair verification, vehicle-specific knowledge, missing vehicle spec handling, G-5 graph integration | **PASS** |
| **AA – AD** | Reasoning trace, JSON serialization round-trip, deterministic analysis repeatability, bounded candidate generation | **PASS** |
| **AE – AG** | Causal depth limit, evidence traversal bound, large evidence set handling (100+ items) | **PASS** |
| **AH – AL** | Safety restrictions, destructive operation rejection, no autonomous repair, no DTC clearing, communication-vs-component distinction | **PASS** |
| **AM – AP** | Alternative candidate preservation, contributing factor classification, confidence component inspection, final verification recommendation | **PASS** |

### 5.2 Regression Test Matrix
Every regression test suite across Phases C through H passed with zero failures:
- `test_phase_h4.py`: 42/42 PASSED (0.009s)
- `test_phase_h3.py`: 35/35 PASSED (0.008s)
- `test_phase_h2.py`: 32/32 PASSED (0.008s)
- `test_phase_h1.py`: 24/24 PASSED (0.006s)
- `test_phase_g_final.py`: 11/11 PASSED (0.161s)
- `test_phase_g5.py`: 41/41 PASSED (0.024s)
- `test_phase_g4.py`: 38/38 PASSED (31.916s)
- `test_phase_g3.py`: 24/24 PASSED (0.008s)
- `test_phase_g2.py`: 46/46 PASSED (31.5s)
- `test_phase_g1.py`: 20/20 PASSED (22.5s)
- `test_phase_f7.py`: 11/11 PASSED (6.2s)
- `test_d_layer_hardening.py`: 8/8 PASSED (0.002s)
- `test_c_layer_integration.py`: 3/3 PASSED (0.001s)

---

## 6. Release Gate Recommendation

**H-4 PASS — READY FOR H-5**
