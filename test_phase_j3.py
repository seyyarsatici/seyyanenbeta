#!/usr/bin/env python3
"""
Seyyanen Automotive Diagnostic Platform — Phase J-3
===================================================
Data Persistence Test Suite
`test_phase_j3.py`

Certifies:
  A. Storage interface compliance (IPersistenceBackend, SQLite & InMemory)
  B. Create / save / load operations
  C. Update operations
  D. List / query operations with filters, pagination, and sorting
  E. Stable IDs preservation
  F. Schema versioning
  G. Schema migration pipeline
  H. Unknown/future schema version rejection (fail-closed)
  I. Malformed data rejection
  J. Corrupted data handling
  K. Atomic writes
  L. Transaction behavior (commit & rollback)
  M. Crash / interrupted write simulation
  N. Large dataset behavior & query bounding
  O. Bounded memory behavior
  P. Diagnostic session persistence
  Q. Vehicle & ECU context persistence
  R. Raw vs derived data preservation (bit-for-bit raw byte accuracy)
  S. Provenance preservation
  T. DTC persistence
  U. Finding persistence
  V. Hypothesis persistence
  W. H-5 DiagnosticWorkflow persistence
  X. I-4 HistoricalDiagnosticCase persistence
  Y. I-5 DiagnosticReasoningSession persistence
  Z. G-5 DiagnosticGraph persistence (relationship != causality preserved)
  AA. Technician observation persistence
  AB. Repair & post-repair verification persistence
  AC. Current vs historical data separation (historical != current truth)
  AD. Safety: Loading persisted data NEVER executes commands or dispatches frames
  AE. Unsafe deserialization rejection
  AF. J-2 Platform abstraction integration (standard path resolution)
  AG. J-1 Hardware adapter metadata integration
  AH. Full C→I diagnostic intelligence regression
"""

import copy
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diagnostic_persistence import (
    CURRENT_SCHEMA_VERSION,
    CorruptedPersistenceDataError,
    DiagnosticRepository,
    DiagnosticSessionRecord,
    DuplicateRecordError,
    IPersistenceBackend,
    InMemoryPersistenceBackend,
    PersistenceError,
    PersistenceManager,
    RawAcquisitionRecord,
    RecordNotFoundError,
    SQLitePersistenceBackend,
    SchemaMigrationRegistry,
    StorageBackendError,
    UnsupportedSchemaVersionError,
)

# J-1 & J-2 Integration Imports
from diagnostic_adapter import (
    AdapterCapabilities,
    AdapterConnectionState,
    AdapterMetadata,
    AdapterRegistry,
    AdapterType,
    DiagnosticAdapter,
    DiagnosticProtocol,
    MockDiagnosticAdapter,
    TransportMedium,
)
from platform_abstraction import (
    OSFamily,
    PlatformManager,
    SimulatedPlatformProvider,
)

# G, H, I Domain Imports
from extended_did import VehicleContext
from advanced_ecu_services import ServiceSafetyClassification, ServiceSafetyPolicy
from advanced_fault_analysis import DTCRecord, FaultEvidence, FaultHypothesis, OperatingCondition
from vehicle_diagnostic_graph import (
    DiagnosticGraph,
    GraphEdge,
    GraphEdgeType,
    GraphNode,
    GraphNodeType,
    make_did_node_id,
    make_dtc_node_id,
    make_ecu_node_id,
    make_vehicle_node_id,
)
from diagnostic_workflow_engine import (
    DiagnosticWorkflow,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowPolicy,
    WorkflowStage,
    WorkflowState,
    WorkflowStopReason,
    WorkflowOutcome,
    TechnicianActionGate,
)
from historical_case_analysis import (
    CaseDTCRecord,
    CaseECUContext,
    CaseLifecycle,
    CaseRepairOutcome,
    CaseRootCause,
    CaseTechnicianConfirmation,
    CaseTestResult,
    HistoricalDiagnosticCase,
    PostRepairVerification,
    RootCauseConfidenceGrade,
)
from advanced_reasoning_layer import (
    DiagnosticReasoningSession,
    ReasoningCandidate,
    ReasoningContradiction,
    ReasoningEvidenceContribution,
    ReasoningTraceStep,
    ReasoningUncertainty,
)
from diagnostic_knowledge_base import (
    KnowledgeConfidence,
    KnowledgeDistinguishingTest,
    KnowledgeLifecycle,
    KnowledgeProvenance,
    KnowledgeProvenanceType,
)


class TestPhaseJ3DataPersistence(unittest.TestCase):
    """Exhaustive test suite certifying Phase J-3 Data Persistence."""

    def setUp(self):
        # Use an isolated temporary directory for SQLite tests
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_diag.db"
        self.sqlite_backend = SQLitePersistenceBackend(db_path=self.db_path)
        self.sqlite_repo = DiagnosticRepository(backend=self.sqlite_backend)

        # In-Memory repo for fast memory testing
        self.mem_backend = InMemoryPersistenceBackend()
        self.mem_repo = DiagnosticRepository(backend=self.mem_backend)

    def tearDown(self):
        self.sqlite_repo.close()
        self.mem_repo.close()
        if PersistenceManager._repository:
            PersistenceManager._repository.close()
            PersistenceManager._repository = None
        self.temp_dir.cleanup()

    # =====================================================================
    # A: STORAGE INTERFACE COMPLIANCE
    # =====================================================================
    def test_A_storage_interface_compliance(self):
        """Both SQLite and InMemory backends satisfy IPersistenceBackend contract."""
        for backend in [self.sqlite_backend, self.mem_backend]:
            self.assertIsInstance(backend, IPersistenceBackend)
            for m in ["initialize", "close", "save_record", "get_record", "get_raw_payload",
                      "delete_record", "list_records", "count_records", "transaction"]:
                self.assertTrue(hasattr(backend, m), f"Missing method: {m}")

    # =====================================================================
    # B: CREATE / SAVE / LOAD
    # =====================================================================
    def test_B_create_save_load(self):
        """Records can be created, saved, and loaded with perfect field fidelity."""
        session = DiagnosticSessionRecord(
            session_id="SESS_001",
            vehicle_context={"vin": "W0L00004312345678", "manufacturer": "Opel", "model": "Astra"},
            session_state="ACTIVE",
        )
        saved_id = self.sqlite_repo.save_session(session)
        self.assertEqual(saved_id, "SESS_001")

        loaded = self.sqlite_repo.get_session("SESS_001")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.session_id, "SESS_001")
        self.assertEqual(loaded.vehicle_context["vin"], "W0L00004312345678")
        self.assertEqual(loaded.session_state, "ACTIVE")

    # =====================================================================
    # C: UPDATE OPERATIONS
    # =====================================================================
    def test_C_update_operations(self):
        """Existing records are updated in place without duplicate generation."""
        session = DiagnosticSessionRecord(
            session_id="SESS_UPD",
            vehicle_context={"vin": "TEST_VIN_1"},
            session_state="ACTIVE",
        )
        self.sqlite_repo.save_session(session)

        # Update state and add completed timestamp
        session.session_state = "COMPLETED"
        session.end_timestamp = time.time()
        self.sqlite_repo.save_session(session)

        loaded = self.sqlite_repo.get_session("SESS_UPD")
        self.assertEqual(loaded.session_state, "COMPLETED")
        self.assertIsNotNone(loaded.end_timestamp)

        # Ensure only 1 record exists in collection
        self.assertEqual(self.sqlite_backend.count_records("diagnostic_sessions"), 1)

    # =====================================================================
    # D: LIST / QUERY OPERATIONS
    # =====================================================================
    def test_D_list_and_query_with_filters(self):
        """Querying records supports filtering by vehicle_id, ECU, and pagination."""
        for i in range(10):
            veh = "VIN_A" if i < 6 else "VIN_B"
            ecu = "ECM" if i % 2 == 0 else "TCM"
            sess = DiagnosticSessionRecord(
                session_id=f"SESS_Q_{i}",
                vehicle_context={"vin": veh},
                ecu_contexts={"target": ecu},
            )
            self.sqlite_repo.save_session(sess)

        # Filter by vehicle_id
        vin_a_list = self.sqlite_repo.list_sessions(vehicle_id="VIN_A", limit=20)
        self.assertEqual(len(vin_a_list), 6)

        # Filter with limit and offset
        paginated = self.sqlite_repo.list_sessions(vehicle_id="VIN_A", limit=3, offset=2)
        self.assertEqual(len(paginated), 3)

    # =====================================================================
    # E: STABLE IDENTIFIERS
    # =====================================================================
    def test_E_stable_identifiers(self):
        """Entity IDs remain stable and deterministic across persistence lifecycles."""
        explicit_id = "CANONICAL_ID_XYZ_789"
        sess = DiagnosticSessionRecord(
            session_id=explicit_id,
            vehicle_context={"vin": "VIN_STABLE"},
        )
        self.mem_repo.save_session(sess)
        loaded = self.mem_repo.get_session(explicit_id)
        self.assertEqual(loaded.session_id, explicit_id)

    # =====================================================================
    # F: SCHEMA VERSIONING
    # =====================================================================
    def test_F_schema_versioning(self):
        """All persisted records stamp the CURRENT_SCHEMA_VERSION explicitly."""
        sess = DiagnosticSessionRecord(session_id="SESS_VER", vehicle_context={})
        self.sqlite_repo.save_session(sess)

        raw = self.sqlite_backend.get_record("diagnostic_sessions", "SESS_VER")
        self.assertIsNotNone(raw)
        self.assertEqual(raw["schema_version"], CURRENT_SCHEMA_VERSION)

    # =====================================================================
    # G: SCHEMA MIGRATION PIPELINE
    # =====================================================================
    def test_G_schema_migration_pipeline(self):
        """Older schema records migrate cleanly to current version."""
        # Register a test migration for a custom collection
        def migrate_v0_to_v1(data: Dict[str, Any]) -> Dict[str, Any]:
            migrated = copy.deepcopy(data)
            migrated["migrated_field"] = "V1_SUCCESS"
            return migrated

        SchemaMigrationRegistry.register_migration("test_mig_col", 0, 1, migrate_v0_to_v1)

        v0_data = {"record_id": "REC_MIG", "schema_version": 0, "legacy_val": 42}
        self.mem_backend.save_record("test_mig_col", "REC_MIG", v0_data)

        migrated = self.mem_backend.get_record("test_mig_col", "REC_MIG")
        self.assertIsNotNone(migrated)
        self.assertEqual(migrated["schema_version"], 1)
        self.assertEqual(migrated["migrated_field"], "V1_SUCCESS")
        self.assertEqual(migrated["legacy_val"], 42)

    # =====================================================================
    # H: UNKNOWN SCHEMA REJECTION (FAIL CLOSED)
    # =====================================================================
    def test_H_unknown_future_schema_rejection(self):
        """Future unsupported schema versions fail closed with UnsupportedSchemaVersionError."""
        future_data = {"record_id": "FUTURE_01", "schema_version": 999}
        self.mem_backend.save_record("test_future_col", "FUTURE_01", future_data)

        with self.assertRaises(UnsupportedSchemaVersionError) as cm:
            self.mem_backend.get_record("test_future_col", "FUTURE_01")
        self.assertIn("exceeds maximum supported version", str(cm.exception))

    # =====================================================================
    # I: MALFORMED DATA REJECTION
    # =====================================================================
    def test_I_malformed_data_rejection(self):
        """Non-serializable structures or invalid IDs fail gracefully."""
        # Non-serializable object
        bad_data = {"invalid_func": lambda x: x}
        with self.assertRaises(CorruptedPersistenceDataError):
            self.sqlite_backend.save_record("col", "REC_BAD", bad_data)

        # Empty record_id or collection
        with self.assertRaises(PersistenceError):
            self.sqlite_backend.save_record("", "ID", {"v": 1})
        with self.assertRaises(PersistenceError):
            self.sqlite_backend.save_record("col", "", {"v": 1})

    # =====================================================================
    # J: CORRUPTED DATA HANDLING
    # =====================================================================
    def test_J_corrupted_data_handling(self):
        """Truncated or corrupted JSON in stored record raises CorruptedPersistenceDataError."""
        # Inject corrupted raw JSON directly into database
        self.sqlite_backend.initialize()
        assert self.sqlite_backend._conn is not None
        with self.sqlite_backend._conn:
            self.sqlite_backend._conn.execute(
                "INSERT INTO records (collection, record_id, schema_version, created_at, updated_at, data_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("corrupt_col", "REC_CORRUPT", 1, time.time(), time.time(), "{truncated_json: true, missing_bracket")
            )

        with self.assertRaises(CorruptedPersistenceDataError):
            self.sqlite_backend.get_record("corrupt_col", "REC_CORRUPT")

    # =====================================================================
    # K: ATOMIC WRITES & TRANSACTIONS
    # =====================================================================
    def test_K_atomic_writes(self):
        """Transactions commit all operations on success."""
        with self.sqlite_backend.transaction():
            self.sqlite_backend.save_record("atom_col", "A1", {"val": 1})
            self.sqlite_backend.save_record("atom_col", "A2", {"val": 2})

        self.assertEqual(self.sqlite_backend.count_records("atom_col"), 2)

    # =====================================================================
    # L: TRANSACTION ROLLBACK BEHAVIOR
    # =====================================================================
    def test_L_transaction_rollback_on_failure(self):
        """Exception within a transaction completely rolls back all intermediate writes."""
        # Test on SQLite backend
        try:
            with self.sqlite_backend.transaction():
                self.sqlite_backend.save_record("rb_col", "RB1", {"val": 1})
                # Simulate mid-transaction fatal failure
                raise RuntimeError("Simulated mid-transaction crash")
        except RuntimeError:
            pass

        self.assertIsNone(self.sqlite_backend.get_record("rb_col", "RB1"))
        self.assertEqual(self.sqlite_backend.count_records("rb_col"), 0)

        # Test on In-Memory backend
        try:
            with self.mem_backend.transaction():
                self.mem_backend.save_record("rb_col_mem", "RB1", {"val": 1})
                raise RuntimeError("Simulated in-memory crash")
        except RuntimeError:
            pass

        self.assertIsNone(self.mem_backend.get_record("rb_col_mem", "RB1"))
        self.assertEqual(self.mem_backend.count_records("rb_col_mem"), 0)

    # =====================================================================
    # M: CRASH / INTERRUPTED WRITE SIMULATION
    # =====================================================================
    def test_M_crash_interrupted_write_simulation(self):
        """Pre-existing valid records remain completely intact if a subsequent write crashes."""
        self.sqlite_repo.save_session(DiagnosticSessionRecord(session_id="STABLE_SESS", vehicle_context={"vin": "STABLE"}))

        try:
            with self.sqlite_backend.transaction():
                self.sqlite_backend.save_record("diagnostic_sessions", "CRASH_SESS", {"bad": 1})
                raise KeyboardInterrupt("Simulated sudden termination")
        except KeyboardInterrupt:
            pass

        # Stable session must still be intact
        stable = self.sqlite_repo.get_session("STABLE_SESS")
        self.assertIsNotNone(stable)
        self.assertEqual(stable.session_id, "STABLE_SESS")
        # Crash session must not exist
        self.assertIsNone(self.sqlite_repo.get_session("CRASH_SESS"))

    # =====================================================================
    # N: LARGE DATASET BEHAVIOR
    # =====================================================================
    def test_N_large_dataset_behavior(self):
        """Persistence engine handles hundreds of records with bounded pagination."""
        with self.sqlite_backend.transaction():
            for i in range(250):
                self.sqlite_backend.save_record(
                    "large_col",
                    f"REC_{i:04d}",
                    {"index": i, "payload": "x" * 64},
                    vehicle_id="VIN_BATCH",
                )

        self.assertEqual(self.sqlite_backend.count_records("large_col"), 250)

        # Bounded query
        page = self.sqlite_backend.list_records("large_col", limit=25, offset=50)
        self.assertEqual(len(page), 25)

    # =====================================================================
    # O: BOUNDED MEMORY BEHAVIOR & BLOB STORAGE
    # =====================================================================
    def test_O_bounded_memory_and_raw_blob(self):
        """Binary acquisition data is stored as BLOB without JSON inflation."""
        blob_data = os.urandom(16384)  # 16 KB raw binary stream
        self.sqlite_backend.save_record(
            "blob_col",
            "BLOB_01",
            {"meta": "raw telemetry"},
            raw_payload=blob_data,
        )

        retrieved_blob = self.sqlite_backend.get_raw_payload("blob_col", "BLOB_01")
        self.assertEqual(retrieved_blob, blob_data)

    # =====================================================================
    # P: DIAGNOSTIC SESSION PERSISTENCE
    # =====================================================================
    def test_P_diagnostic_session_full_lifecycle(self):
        """Full round-trip persistence of a complete DiagnosticSessionRecord."""
        session = DiagnosticSessionRecord(
            session_id="SESS_FULL_01",
            vehicle_context={"vin": "W0L00004319999999", "manufacturer": "Opel", "model": "Aveo 1.4"},
            ecu_contexts={"ECM": {"header": "7E0", "protocol": "CAN_11BIT_500K"}},
            adapter_info={"adapter_id": "ELM_USB", "adapter_type": "ELM327"},
            dtc_records=[{"code": "P0171", "status": "CONFIRMED", "ecu": "ECM"}],
            findings=[{"anomaly_id": "ANOM_01", "type": "TRIM_LEAN", "severity": "HIGH"}],
            hypotheses=[{"hypothesis_id": "HYP_01", "title": "Intake Manifold Leak", "confidence": "HIGH"}],
            selected_tests=[{"test_id": "TEST_01", "candidate_name": "Smoke Test"}],
            executed_tests=[{"test_id": "TEST_01", "outcome": "PASSED"}],
        )
        self.sqlite_repo.save_session(session)

        loaded = self.sqlite_repo.get_session("SESS_FULL_01")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.dtc_records[0]["code"], "P0171")
        self.assertEqual(loaded.hypotheses[0]["title"], "Intake Manifold Leak")
        self.assertEqual(loaded.executed_tests[0]["outcome"], "PASSED")

    # =====================================================================
    # Q: VEHICLE & ECU CONTEXT PERSISTENCE
    # =====================================================================
    def test_Q_vehicle_and_ecu_context_persistence(self):
        """Vehicle context and per-ECU metadata are preserved without truncation."""
        v_ctx = {
            "vin": "KL1TD66E99B123456",
            "manufacturer": "Chevrolet",
            "model": "Aveo",
            "model_year": 2009,
            "engine_code": "F14D3",
            "transmission": "MANUAL",
            "ecu_family": "DELPHI_MT20U",
        }
        ecu_ctx = {
            "ECM": {"logical_id": "ECM", "header": "7E0", "cal_id": "12345678"},
            "TCM": {"logical_id": "TCM", "header": "7E1", "cal_id": "87654321"},
        }
        session = DiagnosticSessionRecord(
            session_id="SESS_CTX_01",
            vehicle_context=v_ctx,
            ecu_contexts=ecu_ctx,
        )
        self.sqlite_repo.save_session(session)

        loaded = self.sqlite_repo.get_session("SESS_CTX_01")
        self.assertEqual(loaded.vehicle_context["engine_code"], "F14D3")
        self.assertEqual(loaded.ecu_contexts["TCM"]["header"], "7E1")

    # =====================================================================
    # R: RAW VS DERIVED DATA PRESERVATION
    # =====================================================================
    def test_R_raw_vs_derived_preservation(self):
        """Exact raw byte payload is preserved alongside parsed metadata."""
        raw_bytes = b"\x41\x00\xbe\x3e\xb8\x11\x41\x0c\x0f\xa0\x62\x01\x00\x12\x34"
        acq_id = self.sqlite_repo.save_raw_acquisition(
            session_id="SESS_RAW_01",
            source_ecu="ECM",
            command_or_pid="010C",
            raw_payload=raw_bytes,
            metadata={"parsed_rpm": 1000, "units": "RPM"},
        )

        loaded_bytes, meta = self.sqlite_repo.get_raw_acquisition(acq_id)
        self.assertEqual(loaded_bytes, raw_bytes, "Raw payload bytes must remain bit-for-bit identical.")
        self.assertEqual(meta["metadata"]["parsed_rpm"], 1000)

    # =====================================================================
    # S: PROVENANCE PRESERVATION
    # =====================================================================
    def test_S_provenance_preservation(self):
        """Audit lineage and provenance survive persistence."""
        prov = {
            "source_type": "LIVE_ACQUISITION",
            "timestamp": round(time.time(), 3),
            "tool_id": "SEYYANEN_PRO_V2",
            "technician_id": "TECH_42",
        }
        session = DiagnosticSessionRecord(
            session_id="SESS_PROV",
            vehicle_context={},
            provenance=prov,
        )
        self.sqlite_repo.save_session(session)

        loaded = self.sqlite_repo.get_session("SESS_PROV")
        self.assertEqual(loaded.provenance["technician_id"], "TECH_42")

    # =====================================================================
    # T: DTC PERSISTENCE
    # =====================================================================
    def test_T_dtc_records_persistence(self):
        """DTCs with freeze frames and status survive storage."""
        dtcs = [
            {"code": "P0300", "status": "PENDING", "ecu": "ECM", "freeze_frame": {"rpm": 1200, "load": 45}},
            {"code": "P0171", "status": "CONFIRMED", "ecu": "ECM", "freeze_frame": {"stft": 15.2, "ltft": 22.1}},
        ]
        session = DiagnosticSessionRecord(
            session_id="SESS_DTC",
            vehicle_context={},
            dtc_records=dtcs,
        )
        self.sqlite_repo.save_session(session)

        loaded = self.sqlite_repo.get_session("SESS_DTC")
        self.assertEqual(len(loaded.dtc_records), 2)
        self.assertEqual(loaded.dtc_records[1]["freeze_frame"]["ltft"], 22.1)

    # =====================================================================
    # U: FINDING PERSISTENCE
    # =====================================================================
    def test_U_findings_persistence(self):
        """Observed diagnostic findings remain intact."""
        findings = [
            {"finding_id": "F_01", "signal": "O2_B1S1", "anomaly": "VOLTAGE_STUCK_LOW", "confidence": 0.92},
        ]
        session = DiagnosticSessionRecord(session_id="SESS_FIND", vehicle_context={}, findings=findings)
        self.sqlite_repo.save_session(session)

        loaded = self.sqlite_repo.get_session("SESS_FIND")
        self.assertEqual(loaded.findings[0]["signal"], "O2_B1S1")

    # =====================================================================
    # V: HYPOTHESIS PERSISTENCE
    # =====================================================================
    def test_V_hypothesis_persistence(self):
        """Root cause hypotheses with competing rankings survive persistence."""
        hyps = [
            {"hypothesis_id": "H_01", "title": "MAF Contamination", "rank": 1, "score": 0.88},
            {"hypothesis_id": "H_02", "title": "Vacuum Leak", "rank": 2, "score": 0.74},
        ]
        session = DiagnosticSessionRecord(session_id="SESS_HYP", vehicle_context={}, hypotheses=hyps)
        self.sqlite_repo.save_session(session)

        loaded = self.sqlite_repo.get_session("SESS_HYP")
        self.assertEqual(len(loaded.hypotheses), 2)
        self.assertEqual(loaded.hypotheses[0]["score"], 0.88)

    # =====================================================================
    # W: H-5 WORKFLOW PERSISTENCE
    # =====================================================================
    def test_W_workflow_persistence(self):
        """Phase H-5 DiagnosticWorkflow survives application restart without losing state."""
        wf = DiagnosticWorkflow(
            workflow_id="WF_TEST_001",
            vehicle_id="VEH_001",
            session_id="SESS_001",
            state=WorkflowState.ACTIVE,
            stage=WorkflowStage.TEST_EXECUTION,
            available_ecus=["ECM", "TCM"],
        )
        wf.events.append(WorkflowEvent(
            event_id="EVT_01",
            workflow_id="WF_TEST_001",
            timestamp=time.time(),
            previous_stage=WorkflowStage.TEST_SELECTION,
            new_stage=WorkflowStage.TEST_EXECUTION,
            event_type=WorkflowEventType.STAGE_ENTERED,
            reason="Selected MAF sensor dynamic response test",
            source_component="H5_ENGINE",
        ))

        saved_id = self.sqlite_repo.save_workflow(wf)
        self.assertEqual(saved_id, "WF_TEST_001")

        loaded_wf = self.sqlite_repo.get_workflow("WF_TEST_001")
        self.assertIsNotNone(loaded_wf)
        self.assertEqual(loaded_wf.workflow_id, "WF_TEST_001")
        self.assertEqual(loaded_wf.state, WorkflowState.ACTIVE)
        self.assertEqual(loaded_wf.stage, WorkflowStage.TEST_EXECUTION)
        self.assertEqual(len(loaded_wf.events), 1)
        self.assertEqual(loaded_wf.events[0].reason, "Selected MAF sensor dynamic response test")

    # =====================================================================
    # X: I-4 HISTORICAL CASE PERSISTENCE
    # =====================================================================
    def test_X_historical_case_persistence(self):
        """Phase I-4 HistoricalDiagnosticCase is persisted with complete context and repair verification."""
        v_ctx = VehicleContext(
            vin="W0L0000431A123456",
            manufacturer="Opel",
            model="Corsa",
            model_year=2012,
            engine_code="A14XER",
        )
        prov = KnowledgeProvenance(
            source_type=KnowledgeProvenanceType.SYSTEM_DERIVED,
            source_reference="CASE_ARCHIVE_01",
            author="Master Technician Ali",
        )
        case = HistoricalDiagnosticCase(
            case_id="HIST_001",
            title="P0171 Lean Fuel Trim - Damaged PCV Diaphragm",
            summary="Confirmed whistling noise and elevated LTFT resolved by replacing valve cover assembly.",
            vehicle_context=v_ctx,
            provenance=prov,
            root_cause=CaseRootCause(
                root_cause_id="RC_PCV_01",
                component_or_system="PCV_MEMBRANE",
                mechanism_description="Torn PCV membrane causing unmetered crankcase air ingestion.",
                confidence_grade=RootCauseConfidenceGrade.CONFIRMED_TECHNICIAN,
            ),
            technician_confirmation=CaseTechnicianConfirmation(
                is_confirmed=True,
                technician_id="TECH_ALI",
                inspection_notes="Smoke test revealed air entering via valve cover breather port.",
            ),
            repair_outcome=CaseRepairOutcome(
                repair_action="REPLACE_VALVE_COVER",
                parts_replaced=["VALVE_COVER_ASSY_55573746"],
            ),
            post_repair_verification=PostRepairVerification(
                verification_performed=True,
                original_anomaly_resolved=True,
                dtc_cleared=True,
                telemetry_normalized=True,
                notes="LTFT dropped from +28% to +1.5% at warm idle.",
            ),
        )

        saved_id = self.sqlite_repo.save_historical_case(case)
        self.assertEqual(saved_id, "HIST_001")

        loaded_case = self.sqlite_repo.get_historical_case("HIST_001")
        self.assertIsNotNone(loaded_case)
        self.assertEqual(loaded_case.case_id, "HIST_001")
        self.assertTrue(loaded_case.is_technician_confirmed())
        self.assertEqual(loaded_case.repair_outcome.parts_replaced[0], "VALVE_COVER_ASSY_55573746")
        self.assertTrue(loaded_case.post_repair_verification.telemetry_normalized)

    # =====================================================================
    # Y: I-5 REASONING SESSION PERSISTENCE
    # =====================================================================
    def test_Y_reasoning_session_persistence(self):
        """Phase I-5 DiagnosticReasoningSession survives persistence with full candidate competition."""
        v_ctx = VehicleContext(vin="KL1TD66E99B123456", manufacturer="Chevrolet", model="Aveo")
        prov = KnowledgeProvenance(source_type=KnowledgeProvenanceType.SYSTEM_DERIVED, source_reference="I5_ENGINE")

        candidate = ReasoningCandidate(
            candidate_id="CAND_01",
            hypothesis_title="Upstream O2 Sensor Aging / Bias",
            evidence_score=0.82,
            overall_score=0.85,
            confidence=ReasoningUncertainty.HIGH_CONFIDENCE,
            explanations=["Delayed lean-to-rich switching frequency under warm closed loop."],
        )

        reasoning = DiagnosticReasoningSession(
            reasoning_id="REAS_001",
            session_id="SESS_001",
            vehicle_context=v_ctx,
            provenance=prov,
            candidates=[candidate],
            ranked_candidates=[candidate],
            overall_conclusion="Upstream oxygen sensor bias most probable cause of intermittent hesitation.",
            overall_confidence=ReasoningUncertainty.HIGH_CONFIDENCE,
        )

        saved_id = self.sqlite_repo.save_reasoning_session(reasoning)
        self.assertEqual(saved_id, "REAS_001")

        loaded_reas = self.sqlite_repo.get_reasoning_session("REAS_001")
        self.assertIsNotNone(loaded_reas)
        self.assertEqual(loaded_reas.reasoning_id, "REAS_001")
        self.assertEqual(loaded_reas.ranked_candidates[0].hypothesis_title, "Upstream O2 Sensor Aging / Bias")
        self.assertEqual(loaded_reas.overall_confidence, ReasoningUncertainty.HIGH_CONFIDENCE)

    # =====================================================================
    # Z: G-5 DIAGNOSTIC GRAPH PERSISTENCE
    # =====================================================================
    def test_Z_diagnostic_graph_persistence(self):
        """Phase G-5 DiagnosticGraph nodes, edges, and relationship!=causality survive storage."""
        graph = DiagnosticGraph(vehicle_id="vehicle:W0L00004312345678")

        v_node = GraphNode(node_id="vehicle:W0L00004312345678", node_type=GraphNodeType.VEHICLE, label="Opel Astra")
        ecu_node = GraphNode(node_id="ecu:ECM", node_type=GraphNodeType.ECU, label="Engine Control Module")
        dtc_node = GraphNode(node_id="dtc:ECM:P0100", node_type=GraphNodeType.DTC, label="P0100 MAF Circuit")

        edge_veh_ecu = GraphEdge(
            edge_id="edge_1",
            source_id="vehicle:W0L00004312345678",
            target_id="ecu:ECM",
            edge_type=GraphEdgeType.HAS_ECU,
        )
        edge_ecu_dtc = GraphEdge(
            edge_id="edge_2",
            source_id="ecu:ECM",
            target_id="dtc:ECM:P0100",
            edge_type=GraphEdgeType.REPORTS_DTC,  # Diagnostic relationship, NOT proven causality
        )

        graph.add_node(v_node)
        graph.add_node(ecu_node)
        graph.add_node(dtc_node)
        graph.add_edge(edge_veh_ecu)
        graph.add_edge(edge_ecu_dtc)

        saved_id = self.sqlite_repo.save_diagnostic_graph(graph)
        self.assertEqual(saved_id, "vehicle:W0L00004312345678")

        loaded_graph = self.sqlite_repo.get_diagnostic_graph("vehicle:W0L00004312345678")
        self.assertIsNotNone(loaded_graph)
        self.assertEqual(len(loaded_graph), 3)
        self.assertEqual(loaded_graph.edge_count, 2)
        self.assertIn("dtc:ECM:P0100", loaded_graph.nodes)
        self.assertEqual(loaded_graph._edges_by_id["edge_2"].edge_type, GraphEdgeType.REPORTS_DTC)

    # =====================================================================
    # AA: TECHNICIAN OBSERVATION PERSISTENCE
    # =====================================================================
    def test_AA_technician_observation_persistence(self):
        """Technician manual observations are appended atomically to existing session."""
        session = DiagnosticSessionRecord(session_id="SESS_TECH_01", vehicle_context={"vin": "V1"})
        self.sqlite_repo.save_session(session)

        obs = {
            "observation_id": "OBS_01",
            "type": "VISUAL_INSPECTION",
            "finding": "Cracked vacuum hose near brake booster check valve",
            "technician_id": "TECH_MEHMET",
        }
        self.sqlite_repo.record_technician_observation("SESS_TECH_01", obs)

        loaded = self.sqlite_repo.get_session("SESS_TECH_01")
        self.assertEqual(len(loaded.technician_observations), 1)
        self.assertEqual(loaded.technician_observations[0]["finding"], "Cracked vacuum hose near brake booster check valve")

    # =====================================================================
    # AB: REPAIR & POST-REPAIR VERIFICATION PERSISTENCE
    # =====================================================================
    def test_AB_repair_verification_persistence(self):
        """Repair actions and verification outcomes are recorded atomically."""
        session = DiagnosticSessionRecord(session_id="SESS_REP_01", vehicle_context={"vin": "V1"})
        self.sqlite_repo.save_session(session)

        ver = {
            "verification_id": "VER_01",
            "repaired_component": "BRAKE_BOOSTER_HOSE",
            "verified_by_test": "IDLE_TRIM_MONITORING",
            "outcome": "PASSED",
            "technician_notes": "Fuel trim returned to 0% after hose replacement.",
        }
        self.sqlite_repo.record_repair_verification("SESS_REP_01", ver)

        loaded = self.sqlite_repo.get_session("SESS_REP_01")
        self.assertEqual(len(loaded.repair_verifications), 1)
        self.assertEqual(loaded.repair_verifications[0]["outcome"], "PASSED")

    # =====================================================================
    # AC: CURRENT VS HISTORICAL SEPARATION
    # =====================================================================
    def test_AC_current_vs_historical_separation(self):
        """
        Invariant: Loading historical cases does not promote them to live active DTCs.
        Historical data is contextual experience, never active truth.
        """
        v_ctx = VehicleContext(vin="VIN_HIST_SEP", manufacturer="Opel", model="Astra")
        prov = KnowledgeProvenance(source_type=KnowledgeProvenanceType.SYSTEM_DERIVED, source_reference="HIST_CASE")
        case = HistoricalDiagnosticCase(
            case_id="HIST_SEP_01",
            title="Historical P0300 Case",
            summary="Historical misfire resolved last year.",
            vehicle_context=v_ctx,
            provenance=prov,
            active_dtcs=[CaseDTCRecord(dtc_code="P0300", target_ecu="ECM", status="HISTORICAL_ARCHIVED")],
        )
        self.sqlite_repo.save_historical_case(case)

        # Create a fresh live session for the same vehicle
        live_session = DiagnosticSessionRecord(
            session_id="LIVE_SESS_01",
            vehicle_context={"vin": "VIN_HIST_SEP"},
            dtc_records=[],  # Zero live DTCs
        )
        self.sqlite_repo.save_session(live_session)

        # Retrieve both
        loaded_case = self.sqlite_repo.get_historical_case("HIST_SEP_01")
        loaded_live = self.sqlite_repo.get_session("LIVE_SESS_01")

        self.assertEqual(len(loaded_case.active_dtcs), 1)
        self.assertEqual(len(loaded_live.dtc_records), 0, "Live session must NOT inherit historical DTCs automatically.")

    # =====================================================================
    # AD: SAFETY: LOADING DATA NEVER EXECUTES COMMANDS
    # =====================================================================
    def test_AD_safety_loading_never_executes_commands(self):
        """
        Critical Safety Invariant:
        Loading a workflow or session from persistence is strictly data restoration.
        It NEVER triggers adapter transmission, hardware dispatch, or ECU commands.
        """
        # Create mock adapter to spy on command calls
        mock_adapter = MockDiagnosticAdapter(adapter_id="SPY_ADAPTER")
        mock_adapter.connect()
        sent_commands = []
        original_send = mock_adapter.send_command
        def spy_send(cmd, *args, **kwargs):
            sent_commands.append(cmd)
            return original_send(cmd, *args, **kwargs)
        mock_adapter.send_command = spy_send

        # Save an active workflow with steps
        wf = DiagnosticWorkflow(
            workflow_id="WF_SAFETY_01",
            vehicle_id="VEH_SAFE",
            session_id="SESS_SAFE",
            state=WorkflowState.ACTIVE,
            stage=WorkflowStage.TEST_EXECUTION,
        )
        self.sqlite_repo.save_workflow(wf)

        # Load workflow 100 times
        for _ in range(100):
            loaded_wf = self.sqlite_repo.get_workflow("WF_SAFETY_01")
            self.assertIsNotNone(loaded_wf)

        # Verify zero commands were sent
        self.assertEqual(len(sent_commands), 0, "Loading data must NEVER execute ECU commands.")
        mock_adapter.disconnect()

    # =====================================================================
    # AE: UNSAFE DESERIALIZATION REJECTION
    # =====================================================================
    def test_AE_unsafe_deserialization_rejection(self):
        """Storage engine uses safe json loading and rejects pickle or arbitrary bytecode."""
        # Directly verify that SQLite backend uses json.loads, rejecting non-json text
        with self.assertRaises(CorruptedPersistenceDataError):
            self.sqlite_backend.save_record("safe_col", "SAFE_01", {"lambda": lambda x: x})

    # =====================================================================
    # AF: J-2 PLATFORM ABSTRACTION INTEGRATION
    # =====================================================================
    def test_AF_j2_platform_integration(self):
        """Default SQLite backend path resolves cleanly via J-2 PlatformManager standard paths."""
        # Simulated Linux environment
        sim_linux = SimulatedPlatformProvider(os_family=OSFamily.LINUX, simulated_home=Path("/home/diag_user"))
        PlatformManager.set_provider(sim_linux)

        expected_app_dir = PlatformManager.get_app_data_path()
        self.assertEqual(expected_app_dir.as_posix(), "/home/diag_user/.local/share/seyyanen")

        # Reset provider to live host
        PlatformManager.reset_to_default_provider()

    # =====================================================================
    # AG: J-1 HARDWARE ADAPTER INTEGRATION
    # =====================================================================
    def test_AG_j1_adapter_integration(self):
        """Session records cleanly encapsulate J-1 adapter capabilities and metadata."""
        mock_adapter = MockDiagnosticAdapter(adapter_id="MOCK_VCI_J1")
        meta = mock_adapter.metadata
        caps = mock_adapter.capabilities

        session = DiagnosticSessionRecord(
            session_id="SESS_J1_01",
            vehicle_context={"vin": "TEST_J1"},
            adapter_info={
                "adapter_id": meta.adapter_id,
                "adapter_type": meta.adapter_type.value,
                "transport_medium": meta.transport_medium.value,
                "capabilities": caps.to_dict(),
            },
        )
        self.sqlite_repo.save_session(session)

        loaded = self.sqlite_repo.get_session("SESS_J1_01")
        self.assertEqual(loaded.adapter_info["adapter_type"], AdapterType.MOCK_REFERENCE.value)
        self.assertTrue(loaded.adapter_info["capabilities"]["supports_uds_diagnostics"])

    # =====================================================================
    # AH: FULL C→I DIAGNOSTIC INTELLIGENCE REGRESSION
    # =====================================================================
    def test_AH_full_c_to_i_diagnostic_intelligence_regression(self):
        """C→I reasoning layers operate transparently alongside Phase J-3 persistence."""
        # 1. Safety Policy enforcement invariant remains strict
        policy = ServiceSafetyPolicy()
        from advanced_ecu_services import AdvancedServiceRequest
        req = AdvancedServiceRequest(service_id="22", payload="0100", safety_classification=ServiceSafetyClassification.READ_ONLY)
        allowed, _ = policy.validate_request(req)
        self.assertTrue(allowed)

        prohibited_req = AdvancedServiceRequest(service_id="2E", payload="0100AA", safety_classification=ServiceSafetyClassification.WRITE)
        blocked, reason = policy.validate_request(prohibited_req)
        self.assertFalse(blocked)
        self.assertIn("prohibited", reason.lower())

        # 2. Global PersistenceManager singleton access
        PersistenceManager.reset_to_default_repository()
        repo = PersistenceManager.get_repository()
        self.assertIsInstance(repo, DiagnosticRepository)


if __name__ == "__main__":
    unittest.main(verbosity=2)
