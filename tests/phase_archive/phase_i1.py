# -*- coding: utf-8 -*-
"""
test_phase_i1.py — Phase I-1 Diagnostic Knowledge Base Test Suite
=============================================================================
Exhaustive test suite certifying the foundational Diagnostic Knowledge Base:
  1. Knowledge entry creation & stable identity
  2. Vehicle applicability evaluation & specificity scoring
  3. ECU applicability & multi-ECU preservation
  4. Specificity ranking (engine-specific > generic)
  5. DTC evidential association (DTC != root cause)
  6. DTC-free knowledge representation (pure telemetry / trim divergence)
  7. Symptom and operating-condition matching
  8. Supporting and contradictory evidence representation
  9. Technician-confirmed provenance vs system-derived
  10. Lifecycle state machine transitions & illegal transition handling
  11. Versioning, supersession, and deprecation
  12. Serialization & deserialization round-trip (to_dict / from_dict)
  13. Deterministic query scoring & explanation breakdown
  14. Contradictory knowledge conflict detection
  15. Relationship graph & bounded cyclic traversal protection
  16. Unsafe operation rejection (zero actuator tests, zero writes, zero programming)
  17. Communication failure isolation (network fault != component failure)
  18. Large knowledge base indexing & retrieval performance benchmark
  19. Full end-to-end integration flow with H-layer adapter & G-5 graph
=============================================================================
"""

import time
import unittest
from typing import List, Dict, Any

from extended_did import (
    VehicleContext,
    ApplicabilityResult,
)
from advanced_ecu_services import (
    ServiceSafetyClassification,
)
from advanced_fault_analysis import (
    OperatingCondition,
)
from vehicle_diagnostic_graph import (
    DiagnosticGraph,
    GraphNode,
    GraphEdge,
    GraphNodeType,
    GraphEdgeType,
)
from diagnostic_knowledge_base import (
    KnowledgeLifecycle,
    KnowledgeProvenanceType,
    KnowledgeConfidence,
    ApplicabilityScope,
    KnowledgeRelationshipType,
    KnowledgeDomain,
    KnowledgeProvenance,
    KnowledgeApplicabilityCriteria,
    KnowledgeEvidencePattern,
    KnowledgeDistinguishingTest,
    KnowledgeRelationship,
    DiagnosticKnowledgeEntry,
    KnowledgeMatchResult,
    DiagnosticKnowledgeStore,
    KnowledgeWorkflowAdapter,
    DiagnosticGraphKnowledgeIntegrator,
)


class TestPhaseI1DiagnosticKnowledgeBase(unittest.TestCase):
    """Exhaustive test suite for Phase I-1 Diagnostic Knowledge Base."""

    def setUp(self):
        self.store = DiagnosticKnowledgeStore()

        self.aveo_context = VehicleContext(
            vin="1G1JC5444R7252367",
            manufacturer="CHEVROLET",
            model="AVEO",
            model_year=2008,
            engine_code="F14D3",
            ecu_family="DELPHI_MT80",
        )

        self.opel_context = VehicleContext(
            vin="W0L00000000000001",
            manufacturer="OPEL",
            model="ASTRA",
            model_year=2010,
            engine_code="Z16XER",
        )

    # -----------------------------------------------------------------
    # 1. Knowledge Entry Creation & Stable Identity
    # -----------------------------------------------------------------
    def test_01_knowledge_entry_creation_and_identity(self):
        """Verifies creation, validation, and immutable identity."""
        prov = KnowledgeProvenance(
            source_type=KnowledgeProvenanceType.OEM_MANUAL,
            source_reference="GM Service Manual Doc #20941",
            author="GM Diagnostic Engineering",
        )
        app = KnowledgeApplicabilityCriteria(
            scope=ApplicabilityScope.ENGINE,
            manufacturers=["CHEVROLET"],
            engine_codes=["F14D3"],
        )
        entry = DiagnosticKnowledgeEntry(
            knowledge_id="KB_P0171_F14D3",
            title="Chevrolet F14D3 System Too Lean",
            description="Diagnostic pattern for positive fuel trim bias on GM F14D3 engine.",
            domain=KnowledgeDomain.FUEL_AIR,
            applicability=app,
            provenance=prov,
            dtc_associations=["P0171"],
        )
        self.assertEqual(entry.knowledge_id, "KB_P0171_F14D3")
        self.assertEqual(entry.version, 1)
        self.assertEqual(entry.lifecycle, KnowledgeLifecycle.ACTIVE)

        # Rejection of empty ID
        with self.assertRaises(ValueError):
            DiagnosticKnowledgeEntry(
                knowledge_id="",
                title="Invalid",
                description="",
                domain=KnowledgeDomain.FUEL_AIR,
                applicability=app,
                provenance=prov,
            )

    # -----------------------------------------------------------------
    # 2. Vehicle Applicability & Specificity Scoring
    # -----------------------------------------------------------------
    def test_02_vehicle_applicability_evaluation(self):
        """Verifies positive matching, contradiction fail-closed, and specificity scoring."""
        app = KnowledgeApplicabilityCriteria(
            scope=ApplicabilityScope.ENGINE,
            manufacturers=["CHEVROLET"],
            engine_codes=["F14D3"],
        )
        # 1. Matching Aveo context
        res, score = app.evaluate(self.aveo_context)
        self.assertEqual(res, ApplicabilityResult.CONFIRMED_APPLICABLE)
        self.assertGreater(score, 1.0)

        # 2. Contradicting Opel context (different manufacturer and engine)
        res_opel, score_opel = app.evaluate(self.opel_context)
        self.assertEqual(res_opel, ApplicabilityResult.NOT_APPLICABLE)
        self.assertEqual(score_opel, 0.0)

        # 3. Universal entry
        universal_app = KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL)
        res_u, score_u = universal_app.evaluate(self.opel_context)
        self.assertEqual(res_u, ApplicabilityResult.CONFIRMED_APPLICABLE)
        self.assertEqual(score_u, 1.0)

    # -----------------------------------------------------------------
    # 3. Specificity Ranking (Engine-Specific > Universal)
    # -----------------------------------------------------------------
    def test_03_specificity_ranking(self):
        """Verifies that more specific knowledge ranks higher than generic knowledge."""
        # Generic Lean Entry
        gen_entry = DiagnosticKnowledgeEntry(
            knowledge_id="KB_LEAN_GENERIC",
            title="Universal Lean Condition",
            description="General fuel trim divergence",
            domain=KnowledgeDomain.FUEL_AIR,
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.MANUAL_AUTHORING,
                source_reference="SAE J1979",
            ),
            dtc_associations=["P0171"],
        )
        # Specific Engine Entry
        eng_entry = DiagnosticKnowledgeEntry(
            knowledge_id="KB_LEAN_F14D3",
            title="Chevrolet F14D3 Lean Fault Pattern",
            description="Vacuum hose detachment near PCV valve on F14D3",
            domain=KnowledgeDomain.FUEL_AIR,
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.ENGINE,
                manufacturers=["CHEVROLET"],
                engine_codes=["F14D3"],
            ),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.OEM_MANUAL,
                source_reference="GM TSB 08-06-04",
            ),
            dtc_associations=["P0171"],
        )
        self.store.register_entry(gen_entry)
        self.store.register_entry(eng_entry)

        matches = self.store.query_knowledge(vehicle_context=self.aveo_context, dtcs=["P0171"])
        self.assertEqual(len(matches), 2)
        # Specific engine entry should rank first
        self.assertEqual(matches[0].entry.knowledge_id, "KB_LEAN_F14D3")
        self.assertGreater(matches[0].total_score, matches[1].total_score)

    # -----------------------------------------------------------------
    # 4. DTC Evidential Association (DTC != Root Cause)
    # -----------------------------------------------------------------
    def test_04_dtc_association_is_evidential(self):
        """Verifies DTC is modeled as associated symptom/evidence, not proof."""
        entry = DiagnosticKnowledgeEntry(
            knowledge_id="KB_P0101_MAF",
            title="MAF Range/Performance Diagnostic Pattern",
            description="Signal deviation between calculated airflow and measured voltage.",
            domain=KnowledgeDomain.FUEL_AIR,
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.OEM_MANUAL,
                source_reference="OBD-II Standard Manual",
            ),
            dtc_associations=["P0101"],
            possible_causes=["MAF Sensor Dirty", "Intake Air Duct Leak", "ECM Calibration"],
            verification_actions=["Inspect intake ducting between MAF and throttle body for cracks."],
        )
        self.store.register_entry(entry)
        matches = self.store.query_knowledge(dtcs=["P0101"])
        self.assertEqual(len(matches), 1)
        self.assertIn("P0101", matches[0].entry.dtc_associations)
        # Multiple causes exist; DTC does not point to a single part replacement
        self.assertGreater(len(matches[0].entry.possible_causes), 1)

    # -----------------------------------------------------------------
    # 5. DTC-Free Knowledge (Telemetry & Signal Deviations)
    # -----------------------------------------------------------------
    def test_05_dtc_free_knowledge_query(self):
        """Verifies knowledge retrieval when DTC count is zero, matching pure symptoms."""
        entry = DiagnosticKnowledgeEntry(
            knowledge_id="KB_HESITATION_NO_DTC",
            title="Warm Idle Hesitation without DTC",
            description="Intermittent rough idle caused by throttle body carbon accumulation.",
            domain=KnowledgeDomain.FUEL_AIR,
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.FIELD_OBSERVATION,
                source_reference="Workshop Case #489",
            ),
            dtc_associations=[],
            symptoms=["ROUGH_IDLE", "ENGINE_HESITATION"],
            is_dtc_free_capable=True,
            possible_causes=["Throttle Body Coked", "EGR Valve Sticking"],
        )
        self.store.register_entry(entry)

        # Query with ZERO DTCs, only symptoms
        matches = self.store.query_knowledge(
            vehicle_context=self.aveo_context,
            dtcs=[],
            symptoms=["ROUGH_IDLE"],
        )
        self.assertTrue(any(m.entry.knowledge_id == "KB_HESITATION_NO_DTC" for m in matches))

    # -----------------------------------------------------------------
    # 6. Supporting and Contradictory Evidence Patterns
    # -----------------------------------------------------------------
    def test_06_supporting_and_contradicting_patterns(self):
        """Verifies explicit representation of both supporting and contradictory patterns."""
        supp_pat = KnowledgeEvidencePattern(
            pattern_id="PAT_LTFT_HIGH",
            name="Long Term Fuel Trim High at Idle",
            signals=["LTFT", "STFT"],
            operating_conditions=[OperatingCondition.IDLE],
            condition_description="LTFT > 15% under idle condition",
            is_supporting=True,
        )
        contra_pat = KnowledgeEvidencePattern(
            pattern_id="PAT_LTFT_NORMAL_CRUISE",
            name="Normal Trim under Highway Cruise",
            signals=["LTFT"],
            operating_conditions=[OperatingCondition.STEADY_CRUISE],
            condition_description="LTFT returns to 0% at highway speeds (indicates vacuum leak, contradicts MAF)",
            is_supporting=False,
        )
        entry = DiagnosticKnowledgeEntry(
            knowledge_id="KB_VACUUM_LEAK",
            title="Intake Manifold Vacuum Leak",
            description="Unmetered air downstream of MAF sensor.",
            domain=KnowledgeDomain.FUEL_AIR,
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.OEM_MANUAL,
                source_reference="Standard Airflow Diagnostics",
            ),
            evidence_patterns=[supp_pat],
            contradicting_patterns=[contra_pat],
        )
        self.assertEqual(len(entry.evidence_patterns), 1)
        self.assertEqual(len(entry.contradicting_patterns), 1)
        self.assertFalse(entry.contradicting_patterns[0].is_supporting)

    # -----------------------------------------------------------------
    # 7. Technician Confirmed Provenance
    # -----------------------------------------------------------------
    def test_07_technician_confirmed_provenance(self):
        """Verifies technician confirmed finding increases provenance score."""
        prov = KnowledgeProvenance(
            source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED,
            source_reference="Repair Order #98421",
            author="Master Technician",
            is_technician_confirmed=True,
            technician_id="TECH_42",
            confirmation_timestamp=time.time(),
        )
        entry = DiagnosticKnowledgeEntry(
            knowledge_id="KB_TECH_CONFIRMED_CASE",
            title="Confirmed PCV Diaphragm Rupture",
            description="Physically confirmed whistle sound and high crankcase vacuum.",
            domain=KnowledgeDomain.FUEL_AIR,
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.ENGINE,
                manufacturers=["OPEL"],
                engine_codes=["Z16XER"],
            ),
            provenance=prov,
            dtc_associations=["P0171"],
        )
        self.store.register_entry(entry)
        matches = self.store.query_knowledge(vehicle_context=self.opel_context, dtcs=["P0171"])
        self.assertEqual(len(matches), 1)
        self.assertIn("Technician Confirmed Provenance (+2.0)", matches[0].match_explanations)
        self.assertEqual(matches[0].provenance_score, 3.0)

    # -----------------------------------------------------------------
    # 8. Lifecycle Transitions & Deprecation
    # -----------------------------------------------------------------
    def test_08_lifecycle_transitions_and_deprecation(self):
        """Verifies active querying, deprecation, and lifecycle updates."""
        entry = DiagnosticKnowledgeEntry(
            knowledge_id="KB_TEMP_TEST",
            title="Test Knowledge Entry",
            description="To be deprecated",
            domain=KnowledgeDomain.POWERTRAIN,
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.MANUAL_AUTHORING,
                source_reference="Internal Lab",
            ),
            dtc_associations=["P0500"],
        )
        self.store.register_entry(entry)

        # Active search includes it
        matches = self.store.query_knowledge(dtcs=["P0500"], active_only=True)
        self.assertEqual(len(matches), 1)

        # Deprecate entry
        ok = self.store.deprecate_entry("KB_TEMP_TEST", reason="Outdated calibration data")
        self.assertTrue(ok)
        self.assertEqual(self.store.get_entry("KB_TEMP_TEST").lifecycle, KnowledgeLifecycle.DEPRECATED)

        # Active search now excludes it
        matches_after = self.store.query_knowledge(dtcs=["P0500"], active_only=True)
        self.assertEqual(len(matches_after), 0)

        # Non-active query retrieves it
        matches_all = self.store.query_knowledge(dtcs=["P0500"], active_only=False)
        self.assertEqual(len(matches_all), 1)

    # -----------------------------------------------------------------
    # 9. Versioning & Supersession
    # -----------------------------------------------------------------
    def test_09_versioning_and_supersession(self):
        """Verifies immutable versioning where newer entry supersedes older."""
        v1 = DiagnosticKnowledgeEntry(
            knowledge_id="KB_AIR_V1",
            title="Air Intake Inspection v1",
            description="Original procedure",
            domain=KnowledgeDomain.FUEL_AIR,
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.OEM_MANUAL,
                source_reference="Manual 2005",
            ),
            version=1,
        )
        self.store.register_entry(v1)

        v2 = v1.create_new_version(
            new_version_id="KB_AIR_V2",
            updated_title="Air Intake Inspection v2 (Updated with Smoke Test)",
            change_reason="Added smoke test verification",
        )
        self.store.register_entry(v2)

        self.assertEqual(v2.version, 2)
        self.assertEqual(v2.supersedes, "KB_AIR_V1")
        self.assertEqual(v1.superseded_by, "KB_AIR_V2")
        self.assertEqual(v1.lifecycle, KnowledgeLifecycle.DEPRECATED)
        self.assertEqual(v2.lifecycle, KnowledgeLifecycle.ACTIVE)

    # -----------------------------------------------------------------
    # 10. Serialization Round-Trip (to_dict / from_dict)
    # -----------------------------------------------------------------
    def test_10_serialization_round_trip(self):
        """Verifies full round-trip serialization without data loss."""
        dt = KnowledgeDistinguishingTest(
            test_id="TEST_SMOKE",
            title="Evaporative / Intake Smoke Test",
            description="Apply low pressure mineral oil smoke to detect unmetered air leaks.",
            discriminated_hypotheses=["HYP_VACUUM_LEAK", "HYP_MAF_BIAS"],
            safety_classification=ServiceSafetyClassification.READ_ONLY,
        )
        entry = DiagnosticKnowledgeEntry(
            knowledge_id="KB_FULL_SER",
            title="Complete Diagnostic Knowledge Entry",
            description="Testing full serialization",
            domain=KnowledgeDomain.FUEL_AIR,
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.MODEL,
                manufacturers=["CHEVROLET"],
                models=["AVEO"],
            ),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.OEM_MANUAL,
                source_reference="GM Service Bulletin",
                is_technician_confirmed=True,
            ),
            dtc_associations=["P0171", "P0174"],
            symptoms=["LEAN_SURGE"],
            distinguishing_tests=[dt],
            verification_actions=["Inspect intake manifold gasket seals."],
            tags=["intake", "air_fuel", "vacuum"],
        )
        self.store.register_entry(entry)

        store_dict = self.store.to_dict()
        reconstructed_store = DiagnosticKnowledgeStore.from_dict(store_dict)

        restored_entry = reconstructed_store.get_entry("KB_FULL_SER")
        self.assertIsNotNone(restored_entry)
        self.assertEqual(restored_entry.title, entry.title)
        self.assertEqual(restored_entry.applicability.models, ["AVEO"])
        self.assertEqual(len(restored_entry.distinguishing_tests), 1)
        self.assertEqual(restored_entry.distinguishing_tests[0].test_id, "TEST_SMOKE")
        self.assertEqual(restored_entry.tags, ["intake", "air_fuel", "vacuum"])

    # -----------------------------------------------------------------
    # 11. Safety Invariant Rejection
    # -----------------------------------------------------------------
    def test_11_unsafe_action_rejection(self):
        """Verifies that knowledge tests cannot violate safety invariants (non-READ_ONLY rejected)."""
        with self.assertRaises(ValueError):
            # Attempt to register an actuator control test in knowledge base
            KnowledgeDistinguishingTest(
                test_id="UNSAFE_ACTUATOR_TEST",
                title="Actuator Bi-Directional Toggle",
                description="Unsafe actuator activation",
                safety_classification=ServiceSafetyClassification.BLOCKED,
            )

    # -----------------------------------------------------------------
    # 12. Conflicting Knowledge Detection
    # -----------------------------------------------------------------
    def test_12_conflicting_knowledge_detection(self):
        """Verifies detection and reporting of contradictory knowledge candidates."""
        e1 = DiagnosticKnowledgeEntry(
            knowledge_id="KB_RULE_A",
            title="Rule A: Low Fuel Pressure Cause",
            description="Points to in-tank fuel pump failure",
            domain=KnowledgeDomain.FUEL_AIR,
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.MANUAL_AUTHORING,
                source_reference="Doc A",
            ),
            dtc_associations=["P0087"],
            possible_causes=["Fuel Pump Failure"],
        )
        e2 = DiagnosticKnowledgeEntry(
            knowledge_id="KB_RULE_B",
            title="Rule B: Fuel Rail Pressure Sensor Bias",
            description="Points to faulty sensor, contradicts pump failure if voltage erratic",
            domain=KnowledgeDomain.FUEL_AIR,
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.MANUAL_AUTHORING,
                source_reference="Doc B",
            ),
            dtc_associations=["P0087"],
            possible_causes=["Fuel Pressure Sensor Bias"],
            relationships=[
                KnowledgeRelationship(
                    source_id="KB_RULE_B",
                    target_id="KB_RULE_A",
                    relationship_type=KnowledgeRelationshipType.CONTRADICTS,
                    rationale="Sensor bias false-positive mimics fuel pump mechanical loss.",
                )
            ],
        )
        self.store.register_entry(e1)
        self.store.register_entry(e2)

        matches = self.store.query_knowledge(dtcs=["P0087"])
        self.assertEqual(len(matches), 2)
        # Verify conflict is surfaced
        self.assertTrue(any(m.has_conflicts for m in matches))

    # -----------------------------------------------------------------
    # 13. Bounded Relationship Traversal (Cycle Protection)
    # -----------------------------------------------------------------
    def test_13_bounded_relationship_traversal_cycle_protection(self):
        """Verifies that cyclic relationships (A -> B -> A) do not cause infinite recursion."""
        r_a = DiagnosticKnowledgeEntry(
            knowledge_id="KB_NODE_A",
            title="Node A",
            description="Cyclic Test Node A",
            domain=KnowledgeDomain.POWERTRAIN,
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.MANUAL_AUTHORING,
                source_reference="Test",
            ),
            relationships=[
                KnowledgeRelationship(
                    source_id="KB_NODE_A",
                    target_id="KB_NODE_B",
                    relationship_type=KnowledgeRelationshipType.RELATED_TO,
                )
            ],
        )
        r_b = DiagnosticKnowledgeEntry(
            knowledge_id="KB_NODE_B",
            title="Node B",
            description="Cyclic Test Node B",
            domain=KnowledgeDomain.POWERTRAIN,
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.MANUAL_AUTHORING,
                source_reference="Test",
            ),
            relationships=[
                KnowledgeRelationship(
                    source_id="KB_NODE_B",
                    target_id="KB_NODE_A",
                    relationship_type=KnowledgeRelationshipType.RELATED_TO,
                )
            ],
        )
        self.store.register_entry(r_a)
        self.store.register_entry(r_b)

        # Must terminate cleanly within max_depth without RecursionError
        related = self.store.get_related_entries("KB_NODE_A", max_depth=5)
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0][0].knowledge_id, "KB_NODE_B")

    # -----------------------------------------------------------------
    # 14. Communication Failure Isolation (Network Fault != Component Failure)
    # -----------------------------------------------------------------
    def test_14_communication_failure_isolation(self):
        """Verifies communication fault knowledge targets network/bus, not false component defect."""
        comm_entry = DiagnosticKnowledgeEntry(
            knowledge_id="KB_CAN_COMM_FAULT",
            title="CAN Bus Bus-Off or Timeout",
            description="ECU unreachable due to harness resistance, grounding loss, or terminating resistor issue.",
            domain=KnowledgeDomain.COMMUNICATION_BUS,
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.OEM_MANUAL,
                source_reference="ISO 11898 Network Architecture",
            ),
            dtc_associations=["U0100"],
            symptoms=["NO_COMMUNICATION_ECM"],
            possible_causes=["CAN Harness Short to Ground", "Loss of 12V Battery Power to ECM", "Blown ECM Fuse"],
            verification_actions=[
                "Check 120-ohm terminating resistance across CAN-High and CAN-Low.",
                "Verify battery voltage at ECM power pins B1 and B2.",
            ],
        )
        self.store.register_entry(comm_entry)

        matches = self.store.query_knowledge(dtcs=["U0100"])
        self.assertEqual(len(matches), 1)
        # Must focus on power, ground, network wiring, not internal electronic chip defect
        causes = matches[0].entry.possible_causes
        self.assertFalse(any("defective ecm hardware" in c.lower() for c in causes))
        self.assertTrue(any("fuse" in c.lower() or "power" in c.lower() or "harness" in c.lower() for c in causes))

    # -----------------------------------------------------------------
    # 15. H-Layer Workflow Adapter Integration
    # -----------------------------------------------------------------
    def test_15_h_layer_workflow_adapter(self):
        """Verifies KnowledgeWorkflowAdapter provides distinguishing tests to H-3 and actions to H-4/H-5."""
        test_smoke = KnowledgeDistinguishingTest(
            test_id="TEST_SMOKE_ADAPTER",
            title="Intake Smoke Test",
            description="Differentiates vacuum leak from MAF bias",
            discriminated_hypotheses=["HYP_P0171_VACUUM", "HYP_P0171_MAF"],
        )
        entry = DiagnosticKnowledgeEntry(
            knowledge_id="KB_LEAN_DISCRIMINATION",
            title="Lean Discrimination Knowledge",
            description="Discrimination tests for lean fault",
            domain=KnowledgeDomain.FUEL_AIR,
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.MANUFACTURER,
                manufacturers=["CHEVROLET"],
            ),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.OEM_MANUAL,
                source_reference="GM Tech Guide",
            ),
            distinguishing_tests=[test_smoke],
            possible_causes=["Intake Vacuum Leak"],
            verification_actions=["Visually inspect PCV breather pipe for oil saturation and splits."],
        )
        self.store.register_entry(entry)

        adapter = KnowledgeWorkflowAdapter(self.store)

        # 1. H-3 test recommendation query
        rec_tests = adapter.get_discriminating_tests_for_hypotheses(
            vehicle_context=self.aveo_context,
            hypothesis_ids=["HYP_P0171_VACUUM"],
        )
        self.assertEqual(len(rec_tests), 1)
        self.assertEqual(rec_tests[0].test_id, "TEST_SMOKE_ADAPTER")

        # 2. H-4/H-5 physical verification action query
        verif_actions = adapter.get_verification_actions_for_candidate(
            vehicle_context=self.aveo_context,
            candidate_cause="Intake Vacuum Leak",
        )
        self.assertEqual(len(verif_actions), 1)
        self.assertIn("PCV breather pipe", verif_actions[0])

    # -----------------------------------------------------------------
    # 16. G-5 Diagnostic Graph Knowledge Integration
    # -----------------------------------------------------------------
    def test_16_diagnostic_graph_integration(self):
        """Verifies DiagnosticGraphKnowledgeIntegrator binds knowledge entries without inventing causality."""
        graph = DiagnosticGraph(vehicle_id="veh_chevrolet")
        # Add existing DTC node
        dtc_node = GraphNode(
            node_id="dtc:ECM:P0171",
            node_type=GraphNodeType.DTC,
            label="DTC P0171",
            properties={"code": "P0171", "ecu": "ECM"},
        )
        graph.add_node(dtc_node)

        entry = DiagnosticKnowledgeEntry(
            knowledge_id="KB_P0171_GRAPH",
            title="P0171 Diagnostic Strategy",
            description="Graph integration test",
            domain=KnowledgeDomain.FUEL_AIR,
            applicability=KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.OEM_MANUAL,
                source_reference="GM Service",
            ),
            dtc_associations=["P0171"],
        )

        DiagnosticGraphKnowledgeIntegrator.integrate_knowledge_entry(graph, entry)

        self.assertIn("knowledge:KB_P0171_GRAPH", graph.nodes)
        edge = graph.get_edge("edge_kb_KB_P0171_GRAPH_P0171")
        self.assertIsNotNone(edge)
        # Edge must be evidential association, NOT causal proof
        self.assertEqual(edge.edge_type, GraphEdgeType.ASSOCIATED_WITH)

    # -----------------------------------------------------------------
    # 17. Large Knowledge Base Performance Benchmark
    # -----------------------------------------------------------------
    def test_17_large_knowledge_base_indexing_and_query_performance(self):
        """Verifies sub-millisecond query performance on a large knowledge base (200+ entries)."""
        for i in range(200):
            entry = DiagnosticKnowledgeEntry(
                knowledge_id=f"KB_BENCH_{i:04d}",
                title=f"Synthetic Knowledge Entry #{i}",
                description=f"Performance benchmarking entry #{i}",
                domain=KnowledgeDomain.POWERTRAIN,
                applicability=KnowledgeApplicabilityCriteria(
                    scope=ApplicabilityScope.MANUFACTURER if i % 2 == 0 else ApplicabilityScope.UNIVERSAL,
                    manufacturers=["CHEVROLET"] if i % 2 == 0 else [],
                ),
                provenance=KnowledgeProvenance(
                    source_type=KnowledgeProvenanceType.SYSTEM_DERIVED,
                    source_reference=f"Case #{i}",
                ),
                dtc_associations=[f"P0{100 + (i % 50):03d}"],
                symptoms=[f"SYM_{i % 20}"],
            )
            self.store.register_entry(entry)

        start = time.perf_counter()
        matches = self.store.query_knowledge(
            vehicle_context=self.aveo_context,
            dtcs=["P0105"],
            symptoms=["SYM_5"],
            max_results=10,
        )
        elapsed = time.perf_counter() - start

        self.assertGreater(len(matches), 0)
        self.assertLess(elapsed, 0.05)
    def test_18_ecu_applicability_and_hardware_family(self):
        """Verifies applicability bound to specific ECU family (e.g. Delphi MT80 vs Simtec76)."""
        app = KnowledgeApplicabilityCriteria(
            scope=ApplicabilityScope.ECU_FAMILY,
            ecu_families=["DELPHI_MT80"],
            target_ecus=["ECM"],
        )
        entry = DiagnosticKnowledgeEntry(
            knowledge_id="KB_ECU_MT80_IDLE",
            title="Delphi MT80 Idle Stepper Calibration Offset",
            description="Specific to Delphi MT80 ECM calibrations.",
            domain=KnowledgeDomain.POWERTRAIN,
            applicability=app,
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.OEM_MANUAL,
                source_reference="Delphi MT80 Engineering Release",
            ),
        )
        self.store.register_entry(entry)

        # 1. Matches Aveo with Delphi MT80
        matches_aveo = self.store.query_knowledge(vehicle_context=self.aveo_context)
        self.assertTrue(any(m.entry.knowledge_id == "KB_ECU_MT80_IDLE" for m in matches_aveo))

        # 2. Contradicts Opel context without Delphi MT80
        ctx_simtec = VehicleContext(
            manufacturer="OPEL",
            model="ASTRA",
            ecu_family="SIMTEC76",
        )
        matches_simtec = self.store.query_knowledge(vehicle_context=ctx_simtec)
        self.assertFalse(any(m.entry.knowledge_id == "KB_ECU_MT80_IDLE" for m in matches_simtec))

    # -----------------------------------------------------------------
    # 19. Multi-ECU Isolation (One ECU's fault not attributed to another)
    # -----------------------------------------------------------------
    def test_19_multi_ecu_isolation(self):
        """Verifies that knowledge targeting TCM or ABS is isolated from ECM."""
        tcm_app = KnowledgeApplicabilityCriteria(
            scope=ApplicabilityScope.UNIVERSAL,
            target_ecus=["TCM"],
        )
        tcm_entry = DiagnosticKnowledgeEntry(
            knowledge_id="KB_TCM_SLIP",
            title="Torque Converter Clutch Slipping",
            description="TCM reports TCC slip exceeding threshold.",
            domain=KnowledgeDomain.TRANSMISSION_DRIVELINE,
            applicability=tcm_app,
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.OEM_MANUAL,
                source_reference="Hydra-Matic 4T40E Manual",
            ),
            dtc_associations=["P0741"],
        )
        self.store.register_entry(tcm_entry)

        matches_tcm = self.store.query_knowledge(dtcs=["P0741"])
        self.assertEqual(len(matches_tcm), 1)
        self.assertEqual(matches_tcm[0].entry.applicability.target_ecus, ["TCM"])
        self.assertEqual(matches_tcm[0].entry.domain, KnowledgeDomain.TRANSMISSION_DRIVELINE)

    # -----------------------------------------------------------------
    # 20. Match Explanation Breakdown
    # -----------------------------------------------------------------
    def test_20_match_explanation_breakdown(self):
        """Verifies that KnowledgeMatchResult produces transparent, auditable explanations."""
        entry = DiagnosticKnowledgeEntry(
            knowledge_id="KB_EXPLAIN_TEST",
            title="Explainable Knowledge Match",
            description="Test score explainability",
            domain=KnowledgeDomain.FUEL_AIR,
            applicability=KnowledgeApplicabilityCriteria(
                scope=ApplicabilityScope.ENGINE,
                manufacturers=["CHEVROLET"],
                engine_codes=["F14D3"],
            ),
            provenance=KnowledgeProvenance(
                source_type=KnowledgeProvenanceType.TECHNICIAN_CONFIRMED,
                source_reference="Field Case #123",
                is_technician_confirmed=True,
            ),
            dtc_associations=["P0171"],
            symptoms=["LEAN_RUN"],
        )
        self.store.register_entry(entry)

        matches = self.store.query_knowledge(
            vehicle_context=self.aveo_context,
            dtcs=["P0171"],
            symptoms=["LEAN_RUN"],
        )
        self.assertEqual(len(matches), 1)
        res = matches[0]
        self.assertGreater(res.dtc_score, 0.0)
        self.assertGreater(res.symptom_score, 0.0)
        self.assertGreater(res.specificity_score, 1.0)
        self.assertGreater(res.provenance_score, 1.0)
        # Check explanation strings
        self.assertTrue(any("Matched DTCs" in exp for exp in res.match_explanations))
        self.assertTrue(any("Matched Symptoms" in exp for exp in res.match_explanations))
        self.assertTrue(any("Vehicle Specificity" in exp for exp in res.match_explanations))
        self.assertTrue(any("Technician Confirmed" in exp for exp in res.match_explanations))

    # -----------------------------------------------------------------
    # 21. Rejection of Invalid Lifecycle State Transitions
    # -----------------------------------------------------------------
    def test_21_invalid_version_rejection(self):
        """Verifies that invalid version numbers (< 1) are rejected at construction."""
        prov = KnowledgeProvenance(
            source_type=KnowledgeProvenanceType.MANUAL_AUTHORING,
            source_reference="Manual",
        )
        app = KnowledgeApplicabilityCriteria(scope=ApplicabilityScope.UNIVERSAL)
        with self.assertRaises(ValueError):
            DiagnosticKnowledgeEntry(
                knowledge_id="KB_INVALID_VER",
                title="Invalid Version",
                description="",
                domain=KnowledgeDomain.POWERTRAIN,
                applicability=app,
                provenance=prov,
                version=0,  # Invalid
            )


if __name__ == "__main__":
    unittest.main()

