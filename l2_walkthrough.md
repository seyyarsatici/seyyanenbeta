# Phase L-2: Dynamic Operating Reference & Context-Aware Expected Behavior

**Seyyanen Automotive Diagnostic Platform — Phase L-2 Technical Walkthrough**

---

## 1. Architectural Overview

Phase L-2 establishes the **conditional, context-aware expected behavior layer** of the Seyyanen diagnostic pipeline. Its purpose is to answer:

> *"For this exact vehicle/engine/ECU, under these exact operating conditions, what behavior should be expected, what is actually happening, and is the deviation diagnostically meaningful?"*

L-2 is **not a diagnosis engine**. It produces structured `ContextualDeviationEvidence` that feeds the existing C→D→H→I reasoning pipeline.

### Data flow

```
Raw acquisition (K-3)
        ↓
C-layer trust/quality validation
        ↓
OperatingContext snapshot (L-2)
        ↓
L-1 VehicleECUKnowledgeStore
        ↓
DynamicOperatingReferenceEngine.evaluate_observation()
        ↓  (resolution hierarchy: baseline > specific > family > generic)
ContextualDeviationEvidence
        ↓
D-1/D-2/D-3 diagnostic fault matrix
        ↓
H-3 EvidenceDrivenTestSelector (missing-context handoff)
        ↓
I-5 AdvancedReasoningEngine
        ↓
H-4 AutomatedRootCauseAnalyzer
```

### Modules

| Module | Role |
|---|---|
| `dynamic_operating_reference.py` | Core L-2 engine: `OperatingContext`, all 5 expectation model classes, `DynamicOperatingReferenceEngine`, `VehicleObservedBaseline`, `BaselineContaminationGuard` |
| `real_vehicle_validation.py` | Real vehicle validation session orchestrator (M-1 boundary) |
| `live_runtime.py` | Extended with `build_operating_context()` — K-3 → L-2 bridge |
| `vehicle_ecu_knowledge.py` | Extended with `get_operating_reference_engine()` — L-1 → L-2 bridge |

---

## 2. Operating Context Model

### `OperatingContext`

Timestamped snapshot of vehicle operating conditions. All variables explicitly carry quality and freshness metadata.

```
OperatingContext
├── timestamp: float
├── vehicle_instance_id: Optional[str]
├── primary_ecu: str
├── variables: Dict[str, OperatingContextVariable]
│     ├── name (normalized UPPER)
│     ├── value: Optional[float]
│     ├── unit: str
│     ├── timestamp: float
│     ├── quality: VariableQuality
│     └── source_ecu: str
└── operating_state: OperatingState
```

### `VariableQuality` taxonomy

| State | Meaning |
|---|---|
| `KNOWN_VALID` | Present, fresh, C-layer quality-checked |
| `UNKNOWN` | Not acquired this cycle |
| `STALE` | Timestamp exceeds freshness threshold |
| `INVALID` | Failed quality gate |
| `IMPLAUSIBLE` | Physical plausibility rejected |

`None` value → automatically assigned `UNKNOWN`. Unknown is never silently treated as zero.

### Operating state classification

Evidence-based deterministic classification. Returns `UNKNOWN_STATE` whenever RPM is missing:

| State | Evidence condition |
|---|---|
| `ENGINE_OFF` | RPM < 50 |
| `CRANKING` | 50 ≤ RPM < 450 |
| `COLD_START` | RPM ≥ 450, ECT < 45°C, stationary, closed throttle |
| `WARMING` | 45 ≤ ECT < 75°C |
| `WARM_IDLE` | 500 ≤ RPM ≤ 1050, ECT ≥ 75°C, stationary, closed throttle |
| `IDLE` | 500 ≤ RPM ≤ 1050, stationary, closed throttle |
| `DECELERATION` | Speed > 20, closed throttle, RPM > 1200 |
| `HIGH_LOAD` | Engine load > 75% |
| `STEADY_CRUISE` | Speed > 40, partial throttle, moderate load |
| `PART_LOAD` | RPM ≥ 1050 (fallback) |
| `UNKNOWN_STATE` | Insufficient evidence |

### Contradiction detection

Explicit physical consistency checks:
1. Engine standstill (RPM < 50) while speed > 15 km/h
2. WOT (TPS > 80%) with MAP < 25 kPa
3. Engine off (RPM < 50) with load > 20%

Returns `List[str]` of human-readable contradiction descriptions. Contradictions produce `CONTRADICTORY_CONTEXT` evidence, not silent failures.

---

## 3. Expectation Model Architecture

### Class hierarchy

```
ExpectedBehaviorModel (abstract)
├── FixedRangeExpectationModel          (static physical envelope)
├── ContextDependentRangeModel          (dynamic bounds from operating context)
├── RelationshipExpectationModel        (cross-sensor coherence)
├── TemporalExpectationModel            (rate-of-change, frozen, monotonic)
└── UnavailableExpectationModel         (explicit absence — NO_REFERENCE)
```

All models are explicit about their `model_id`, `signal_id`, `provenance`, `applicability`, and `target_ecu`.

### `ContextDependentRangeModel` evaluation pipeline

1. **Completeness**: required variables must be `KNOWN_VALID`
2. **Freshness**: variables must be within `max_context_age` seconds
3. **Contradiction**: physical consistency check
4. **Sample validity**: NaN / None → `INVALID_SAMPLE`
5. **Dynamic range**: `range_evaluator(ctx)` → `(min, max)` or `None`
6. **Result**: `EXPECTED_CONFORMANT` / `DEVIATION` / `UNKNOWN_EXPECTATION`

### `TemporalExpectationModel` features

| Feature | Configurable field | Trigger |
|---|---|---|
| Rate-of-change limit | `max_rate_of_change_per_s` | `\|Δv/Δt\| > limit` → DEVIATION STRONG |
| Frozen signal | `max_frozen_duration_s` | Stuck beyond duration → DEVIATION MODERATE |
| Warm-up monotonicity | `require_monotonic_increase` | Drop > 2°C during COLD_START/WARMING → DEVIATION |

### `RelationshipExpectationModel`

Cross-sensor physical coherence via callable `relationship_check(actual, related, ctx) → (is_coherent, deviation_metric, reason)`. Checks related signal freshness and usability before evaluation.

---

## 4. Provenance System

| `ExpectationProvenanceType` | Authority |
|---|---|
| `OEM_SPECIFICATION` | OEM / SAE standards documentation |
| `ENGINEERING_DERIVED` | Physical model with engineering justification |
| `VEHICLE_OBSERVED_BASELINE` | Empirical baseline from specific vehicle instance |
| `TECHNICIAN_CONFIRMED` | Technician-validated baseline |
| `HEURISTIC_INFERENCE` | Derived heuristic (lowest authority) |
| `UNKNOWN_PROVENANCE` | No trustworthy source → `UNKNOWN_EXPECTATION` |

No values are fabricated. If no authoritative source exists, `UnavailableExpectationModel` is returned.

---

## 5. Evidence Output: `ContextualDeviationEvidence`

### Status taxonomy

| `ExpectationStatus` | Verdict |
|---|---|
| `EXPECTED_CONFORMANT` | **NORMAL** — within expected envelope |
| `DEVIATION` | **DEVIATION** — outside expected envelope |
| `INSUFFICIENT_CONTEXT` | **INSUFFICIENT_CONTEXT** — required signals missing |
| `STALE_CONTEXT` | **INSUFFICIENT_CONTEXT** (stale) |
| `CONTRADICTORY_CONTEXT` | **INCONCLUSIVE** — physical contradiction |
| `UNKNOWN_EXPECTATION` | **NO_REFERENCE** — no authoritative model |
| `INVALID_SAMPLE` | **INVALID** — NaN/None observation |

`INSUFFICIENT_CONTEXT` names exactly which signals are missing in `reason`, feeding H-3 test selection.

### `EvidencePolarity`

| Value | Diagnostic meaning |
|---|---|
| `SUPPORTING` | Supports normal operation / refutes fault hypothesis |
| `CONTRADICTING` | Supports fault hypothesis |
| `INSUFFICIENT` | Cannot determine — missing/stale/contradictory context |

### Integration adapters

| Method | Destination |
|---|---|
| `to_c_layer_evidence_status()` | C/D-layer legacy string constants |
| `to_reasoning_evidence_contribution()` | I-5 `ReasoningEvidenceContribution` |
| `to_structured_diagnostic_evidence()` | D-layer `StructuredDiagnosticEvidence` |

---

## 6. Vehicle Observed Baseline

Instance-specific empirical reference from clean, verified vehicle operation:

- Key: `"{instance_id}:{signal_id}:{operating_state}"`
- `plausible_bounds` = 3-sigma envelope bounded by observed min/max
- Evaluation priority: baseline > registered model > generic

### Baseline Contamination Guard

Static guard (`BaselineContaminationGuard.can_ingest_sample()`) rejects samples from:

- Active fault periods
- Active DTCs present
- Invalid communication status (not `STATUS_VALID`)
- Non-`KNOWN_VALID` sample quality
- NaN/None values
- Contradictory operating context

---

## 7. Built-in Standard Models

| Model ID | Signal | Type | Justification |
|---|---|---|---|
| `OEM_SPEC_ECT_WARM_OPERATING` | ECT | Fixed 75–110°C | SAE/OEM warm ICE thermostat operating range |
| `ENG_DERIVED_MAP_DYNAMIC_ENVELOPE` | MAP | Context-dependent by state | Physical manifold vacuum physics |
| `ENG_DERIVED_MAF_LOAD_CORRELATION` | MAF vs LOAD | Relationship | Mass-flow vs calculated load coherence |
| `ENG_DERIVED_SPEED_RPM_CORRELATION` | SPEED vs RPM | Relationship | Standstill/movement coherence |
| `ENG_DERIVED_ECT_TEMPORAL_MONITOR` | ECT | Temporal (5°C/s, 300s frozen, monotonic) | Coolant thermal inertia physics |

MAP conditioning (engineering-derived, not fabricated):

| Operating State | Expected MAP range |
|---|---|
| ENGINE_OFF | 90–105 kPa (atmospheric) |
| IDLE / WARM_IDLE | 24–48 kPa (high manifold vacuum) |
| DECELERATION | 15–32 kPa (peak vacuum overrun) |
| HIGH_LOAD | 80–115 kPa (near atmospheric / boosted) |
| PART_LOAD | 35–80 kPa |

---

## 8. Resolution Hierarchy

`DynamicOperatingReferenceEngine.resolve_model()` scoring (mirrors L-1 specificity):

| Priority | Condition | Score |
|---|---|---|
| 1 | Vehicle instance baseline | Returned directly before model lookup |
| 2 | `CONFIRMED_APPLICABLE` + specific OEM rule | 95 |
| 3 | `CONFIRMED_APPLICABLE` generic | 50 |
| 4 | `LIKELY_APPLICABLE` + specific | 35 |
| 5 | `LIKELY_APPLICABLE` generic | 30 |
| 6 | ECU target match bonus | +15 |

`NOT_APPLICABLE` models are excluded. More specific evidence always wins.

---

## 9. K-3 / L-1 Integration

### K-3 bridge: `LiveAcquisitionRuntime.build_operating_context()`

Reads `_latest_successful_by_pid` cache (K-3 bounded history) and maps standard OBD PID codes to `OperatingContext` variables:

```
PID 010C → RPM
PID 0105 → ECT
PID 010B → MAP
PID 010D → SPEED
PID 0111 → TPS
PID 0104 → LOAD
PID 010F → IAT
```

Returns typed `OperatingContext` with correct `vehicle_instance_id`. No new persistence or acquisition logic.

### L-1 bridge: `VehicleECUKnowledgeStore.get_operating_reference_engine()`

Returns the `DynamicOperatingReferenceEngine` instance bound to `self` (the knowledge store). Provides a single integrated lookup path: L-1 identity → L-2 expectation.

---

## 10. H-3 Missing-Data Handoff

```python
# Pattern: missing context signals → H-3 test selection
evidence = engine.evaluate_observation("MAP_INJECTOR_PULSE", value, ctx)
if evidence.status == ExpectationStatus.INSUFFICIENT_CONTEXT:
    missing_signals = parse_missing_from_reason(evidence.reason)
    # H-3 EvidenceDrivenTestSelector.select_tests(missing_signals, ...)
```

L-2 identifies missing signals. H-3 decides which tests to add. L-2 does not create a parallel test-selection engine.

---

## 11. Real Vehicle Validation Workflow

### Distinction

| Status | Meaning |
|---|---|
| `UNIT_SYNTHETIC_VALIDATED` | Deterministic fixture-based automated tests |
| `REAL_VEHICLE_VALIDATED` | Physical vehicle data collected and documented |

**Current status: `UNIT_SYNTHETIC_VALIDATED`**

### Required for `REAL_VEHICLE_VALIDATED`

1. Physical VCI adapter connected to a real vehicle
2. Vehicle identity confirmed (VIN, engine code, ECU ID)
3. Live acquisition session with K-3 quality gates passing
4. Technician-reviewed procedure results
5. `VehicleObservedBaseline(is_technician_confirmed=True)` explicitly set
6. Session record stored in J-3 `DiagnosticRepository`

### Validation procedures (defined in `real_vehicle_validation.py`)

| Procedure | Target state | Required signals |
|---|---|---|
| A. Key-on / engine-off | ENGINE_OFF | RPM, MAP |
| B. Cold start | COLD_START | RPM, ECT, MAP, MAF |
| C. Warm idle | WARM_IDLE | RPM, ECT, MAP, TPS, LOAD |
| D. Steady idle | IDLE | RPM, ECT, MAP, TPS |
| E. Light throttle | TRANSIENT | RPM, TPS, MAP, LOAD |
| F. Steady cruise | STEADY_CRUISE | RPM, SPEED, TPS, LOAD |
| G. Acceleration/load | HIGH_LOAD | RPM, LOAD, MAP, MAF |
| H. Deceleration | DECELERATION | RPM, SPEED, TPS, MAP |
| I. Vehicle-specific | Per vehicle | Per procedure |

---

## 12. Performance Benchmarks

Measured Windows host, Python 3.14, 10,000 iterations:

| Operation | Latency |
|---|---|
| MAP context-dependent evaluation | **14.3 µs/iter** |
| ECT fixed-range evaluation | **11.4 µs/iter** |
| MAF relationship evaluation | **29.0 µs/iter** |
| Operating state classification | **5.3 µs/iter** |
| 50,000-sample large-log throughput | **~70,000 evals/s (715 ms)** |

Design properties:
- No disk I/O during evaluation — all lookups in-memory
- Model lookup is dict-keyed O(1), not O(N) scan
- No O(N²) comparisons
- Bounded baseline store; no unbounded history accumulation

---

## 13. Safety Boundaries

L-2 is strictly read/analysis-only:

| Prohibited | Status |
|---|---|
| ECU memory writes (0x2E) | Never present |
| DTC clearing (0x14) | Never present |
| Security access (0x27) | Never present |
| Actuation (0x2F) | Never present |
| Flashing (0x34–0x37) | Never present |
| Coding (0x3D) | Never present |

No `evaluate_*` method can trigger any ECU write. All physical test execution remains behind J-5 `SecurityManager` and J-1 adapter safety gates.

---

## 14. Known Limitations

1. **No OEM specification database**: Vehicle-specific numeric references require explicit OEM documentation. Engineering models are the fallback.
2. **DYNAMIC_RESPONSE model type defined but not populated**: Transient response timing (settling time, response delay) not built-in.
3. **Fuel trim, injector PW, lambda built-ins absent**: High variability across strategies — must be registered per vehicle with explicit provenance.
4. **Altitude/barometric correction not automatic**: MAP bounds are sea-level defaults. Correction requires BARO in context.
5. **No automatic model learning**: Deterministic and auditable by design. Baseline updates require explicit contamination guard pass + technician confirmation.
6. **Real vehicle validation not yet performed**: All tests are synthetic fixture-based.

---

## 15. Test Matrix

| Test | Requirement |
|---|---|
| A. Context construction | Variable creation, normalization, quality |
| B. Context completeness | `check_completeness()` |
| C. Context freshness | `check_freshness()` |
| D. Stale context rejection | Stale → `STALE_CONTEXT` + `INSUFFICIENT` polarity |
| E. Contradictory detection | Contradiction → `CONTRADICTORY_CONTEXT` |
| F. State classification | 8 states from evidence |
| G. Fixed expectation | ECT in/out of range |
| H. Context-dependent | MAP at warm idle |
| I. Relationship | MAF vs LOAD coherence |
| J. Temporal | Rate-of-change spike, frozen sensor |
| K. Unknown signal | `UNKNOWN_EXPECTATION`, no fabrication |
| L. Vehicle-specific | VW BAG model vs Opel |
| M. ECU-specific | TCM model not resolved for ECM query |
| N. Provenance | `OEM_SPECIFICATION` vs `ENGINEERING_DERIVED` |
| O. No fabricated values | Unmodeled signal → UNKNOWN |
| P. Missing context | MAP without RPM → `INSUFFICIENT_CONTEXT` |
| Q. Failed sample | NaN → `INVALID_SAMPLE` |
| R. Baseline contamination | Active fault / DTC / timeout rejection |
| S. Trusted baseline | Instance baseline priority and isolation |
| T. Evidence structure | All fields present in `to_dict()` |
| U. DTC-free anomaly | Deviation detectable with 0 active DTCs |
| V. Contradictory evidence | Divergent signals preserved without averaging |
| W. Heuristic score | `to_reasoning_evidence_contribution()` weight |
| X. D/H/I integration | `to_structured_diagnostic_evidence()`, `to_c_layer_evidence_status()` |
| Y. Multi-ECU isolation | ECM vs TCM evaluation isolation |
| Z. Timestamp correctness | Fixed timestamp preserved in evidence |
| AA. Performance | 1000 evals < 0.2s |
| AB. Safety separation | No destructive service methods on engine |
| AC. K-3 integration | `build_operating_context()` from PID cache |
| AD. L-1 integration | `get_operating_reference_engine()` returns bound engine |
| AE. J-Final regression | J-5 security contract unchanged |

---

## 16. Regression Status

| Suite | Count | Status |
|---|---|---|
| L-2 (`test_phase_l2.py`) | 31 | **PASS** |
| L-1 (`test_phase_l1.py`) | 26 | **PASS** |
| K-3/K-2/K-1 | 66 | **PASS** |
| J-1 through J-Final | 197 | **PASS** |
| C/D/F/G/H/I suites | 62 | **PASS** |
| **Total** | **382** | **0 FAILURES** |

---

## L-2 VERDICT

> ## L-2 PASS — READY FOR REAL VEHICLE VALIDATION

All automated tests pass. Implementation is structurally complete.
Real physical vehicle evidence has **not yet been collected**.

Physical validation status: **UNIT_SYNTHETIC_VALIDATED**
Real vehicle validation status: **PENDING**
