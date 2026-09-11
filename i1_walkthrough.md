# Phase I-1: Diagnostic Knowledge Base — Release Walkthrough

## 1. Executive Summary

Phase I-1 initiates the Intelligence and Knowledge Layer of the Seyyanen Automotive Diagnostic Platform with the creation of the **Diagnostic Knowledge Base Subsystem** (`diagnostic_knowledge_base.py`).

Phase I-1 bridges the deterministic automation of Phase H with structured, evidence-oriented, reusable diagnostic knowledge. It strictly prevents transforming Seyyanen into an ungrounded or hallucinating AI chatbot database:
```
Raw Observation (F)
  → Validated Evidence (D / G-2)
  → Diagnostic Finding (G-3 / G-4)
  → Hypotheses (G-3 / G-5)
  → Confirmed Root Cause (H-4 / H-5)
  → Reusable Diagnostic Knowledge Base (I-1)
```

### Delegation vs Orchestration Boundary
- **C through H**: Retain exclusive control over live transport, data safety policies, automated sequencing, test selection, root-cause ranking, and workflow orchestration.
- **I-1**: Implements the foundational, immutable knowledge representation, vehicle/ECU applicability envelope, evidential pattern descriptions, and deterministic specificity-ranked retrieval engine.
- **Strict Safety Invariant**: Diagnostic Knowledge entries are strictly advisory and evidential. Under no circumstances can knowledge entries bypass H-1/H-2 safety controls or directly dispatch prohibited services (`Mode 04/14`, `0x2E`, `0x27`, `0x2F`, `0x34/36/37`).

**Release Gate Status**: **`I-1 PASS — READY FOR I-2`**

---

## 2. Implemented Models & Subsystem Features

### 2.1 Enumerations & Taxonomy
1. **`KnowledgeLifecycle`**:
   - `DRAFT`, `CANDIDATE`, `VALIDATED`, `ACTIVE`, `DEPRECATED`, `REJECTED`.
2. **`KnowledgeProvenanceType`**:
   - `OEM_MANUAL`, `TECHNICAL_SERVICE_BULLETIN`, `TECHNICIAN_CONFIRMED`, `VALIDATED_PROCEDURE`, `SYSTEM_DERIVED`, `FIELD_OBSERVATION`, `MANUAL_AUTHORING`.
3. **`KnowledgeConfidence`**:
   - `CONFIRMED`, `HIGH`, `MODERATE`, `LOW`, `PROVISIONAL`.
4. **`ApplicabilityScope`**:
   - `UNIVERSAL`, `MANUFACTURER`, `MODEL`, `GENERATION`, `ENGINE`, `TRANSMISSION`, `ECU_FAMILY`, `CALIBRATION`, `INSTANCE`.
5. **`KnowledgeRelationshipType`**:
   - `RELATED_TO`, `SUPPORTS`, `CONTRADICTS`, `REFINES`, `SUPERSEDES`, `DERIVED_FROM`, `APPLIES_TO`, `DISTINGUISHES`, `REQUIRES_VERIFICATION`, `CAUSES`.
6. **`KnowledgeDomain`**:
   - `POWERTRAIN`, `FUEL_AIR`, `IGNITION`, `EXHAUST_EMISSIONS`, `ELECTRICAL_NETWORK`, `CHASSIS_BRAKES`, `BODY_SECURITY`, `THERMAL_MANAGEMENT`, `TRANSMISSION_DRIVELINE`, `COMMUNICATION_BUS`.

### 2.2 Foundational Data Models
- **`KnowledgeProvenance`**:
  - Full audit trail recording source documents, authors, timestamps, and explicit technician confirmation status (`is_technician_confirmed`, `technician_id`, `confirmation_timestamp`).
- **`KnowledgeApplicabilityCriteria`**:
  - Evaluates matching against `VehicleContext` deterministically. Enforces fail-closed negative matching on vehicle contradictions and calculates specificity weights (Engine > Model > Manufacturer > Universal).
- **`KnowledgeEvidencePattern`**:
  - Encapsulates reusable signal patterns (e.g. `LTFT > 15% at warm idle`) and specifies whether a pattern is supporting or contradictory.
- **`KnowledgeDistinguishingTest`**:
  - Connects competing hypotheses to recommended observational tests. Enforces `safety_classification == READ_ONLY` in post-init validation.
- **`KnowledgeRelationship`**:
  - Directed links between entries preserving confidence, rationale, and timestamps.
- **`DiagnosticKnowledgeEntry`**:
  - Complete, first-class knowledge entity providing `to_dict()`, `from_dict()`, and `create_new_version()`.

### 2.3 Store & Query Engine (`DiagnosticKnowledgeStore`)
- **Multi-Key Secondary Indexes**:
  - Fast lookup indexed by DTC, symptom, vehicle manufacturer, engine code, functional domain, and lifecycle state.
- **Explainable Retrieval Scoring**:
  - `KnowledgeMatchResult` outputs a transparent score breakdown: specificity weight + DTC matches + symptom matches + provenance bonuses.
- **Conflict Detection**:
  - Automatically identifies when two matching candidates contain mutual `CONTRADICTS` relationships, surfacing warnings rather than silently merging them.
- **Bounded Relationship Traversal**:
  - Recursion depth limits with visited-set tracking prevent infinite loops on cyclic relationships.

### 2.4 H-Layer & G-5 Integrators
- **`KnowledgeWorkflowAdapter`**:
  - Provides H-3 (`EvidenceDrivenTestSelector`) with distinguishing tests for competing active hypotheses.
  - Provides H-4 / H-5 with recommended technician verification actions for leading candidates.
- **`DiagnosticGraphKnowledgeIntegrator`**:
  - Maps knowledge entries to G-5 `DiagnosticGraph` nodes (`EVIDENCE`) and edges (`ASSOCIATED_WITH`).
  - Preserves the invariant: `RELATIONSHIP != CAUSALITY`.

---

## 3. Core Architectural Invariants Verified

1. **DTC != Root Cause**:
   - Modeled as an evidential association (`dtc_associations`), pointing to multiple possible causes and requiring distinguishing tests.
2. **Correlation != Causation**:
   - Relationships default to evidential/structural associations (`RELATED_TO`, `ASSOCIATED_WITH`). Causal claims require physical grounding.
3. **Communication Failure != Component Failure**:
   - `KB_CAN_COMM_FAULT` correctly guides investigation to harness wiring, fuses, and power ground, never claiming defective internal electronics.
4. **DTC-Free Telemetry Diagnosis**:
   - Reusable patterns operate effectively with zero DTCs, matching symptoms like `ROUGH_IDLE` or `LEAN_SURGE` directly against live signal deviations.
5. **Safety Boundary**:
   - `KnowledgeDistinguishingTest` rejects non-read-only safety classifications at construction.

---

## 4. Test Suite Execution & Results

### Dedicated Phase I-1 Suite
```powershell
python -m unittest test_phase_i1.py
```
**Results**: 21 tests run in 0.005s — **0 failures, 0 errors (OK)**.

Scenarios verified:
- `test_01_knowledge_entry_creation_and_identity`: Pass
- `test_02_vehicle_applicability_evaluation`: Pass
- `test_03_specificity_ranking`: Pass
- `test_04_dtc_association_is_evidential`: Pass
- `test_05_dtc_free_knowledge_query`: Pass
- `test_06_supporting_and_contradicting_patterns`: Pass
- `test_07_technician_confirmed_provenance`: Pass
- `test_08_lifecycle_transitions_and_deprecation`: Pass
- `test_09_versioning_and_supersession`: Pass
- `test_10_serialization_round_trip`: Pass
- `test_11_unsafe_action_rejection`: Pass
- `test_12_conflicting_knowledge_detection`: Pass
- `test_13_bounded_relationship_traversal_cycle_protection`: Pass
- `test_14_communication_failure_isolation`: Pass
- `test_15_h_layer_workflow_adapter`: Pass
- `test_16_diagnostic_graph_integration`: Pass
- `test_17_large_knowledge_base_indexing_and_query_performance`: Pass (< 50ms)
- `test_18_ecu_applicability_and_hardware_family`: Pass
- `test_19_multi_ecu_isolation`: Pass
- `test_20_match_explanation_breakdown`: Pass
- `test_21_invalid_version_rejection`: Pass

### Phase H + Phase I-1 Regression
```powershell
python -m unittest test_phase_i1.py test_phase_h_final.py test_phase_h5.py test_phase_h4.py test_phase_h3.py test_phase_h2.py test_phase_h1.py
```
**Results**: 224 tests run in 0.093s — **0 failures, 0 errors (OK)**.

---

## 5. Scope Boundary & Next Steps
- Strictly foundational knowledge base (I-1).
- No historical case database or learning algorithms (reserved for I-2 / I-3).
- No external machine learning training models or chatbot backends.

---

I-1 PASS — READY FOR I-2
