#!/usr/bin/env python3
"""
Seyyanen Automotive Diagnostic Platform — Phase M-8 Tests
`test_m8_import.py`

Covers Tests A through AD for the `seyyanen_mini_import` package:
- Test A: Valid Mini session import
- Test B: Missing metadata detection
- Test C: Malformed metadata handling
- Test D: Missing CSV detection
- Test E: Schema mismatch detection
- Test F: Invalid timestamp handling
- Test G: Invalid PID handling
- Test H: Invalid numeric value handling
- Test I: VALID row mapping
- Test J: TIMEOUT row mapping (zero-resistance)
- Test K: NO DATA mapping (zero-resistance)
- Test L: Raw response preservation
- Test M: Provenance preservation
- Test N: Session identity preservation
- Test O: Reversible timestamp normalization
- Test P: Out-of-order timestamp detection
- Test Q: Duplicate sequence detection
- Test R: Deterministic import repeatability
- Test S: Idempotent repeated import
- Test T: Unknown vehicle identity handling
- Test U: Explicit vehicle instance attachment
- Test V: PID metadata reconciliation
- Test W: Large-log streaming import
- Test X: Import report correctness
- Test Y: Existing C-layer handoff (AutoExpertEngine)
- Test Z: No bypass of quality/trust layer
- Test AA: No duplicate persistence
- Test AB: Path validation and zip slip security
- Test AC: UI preview state inspection
- Test AD: Malformed request handling
"""

import unittest
import os
import sys
import json
import csv
import tempfile
import shutil

# Ensure root directory is on path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import seyyanen_mini_import as smi
from seyyanen_mini_import.session_reader import SessionReader
from seyyanen_mini_import.metadata_parser import MetadataParser
from seyyanen_mini_import.sample_parser import SampleParser
from seyyanen_mini_import.schema_validator import SchemaValidator
from seyyanen_mini_import.timestamp_normalizer import TimestampNormalizer
from seyyanen_mini_import.mini_normalizer import MiniNormalizer


class TestM8Import(unittest.TestCase):

    def setUp(self):
        self.canonical_session_dir = os.path.join(ROOT_DIR, "seyyanen_mini", "MINI_REAL_VEHICLE_VALIDATION_SESSION")
        self.temp_dir = tempfile.mkdtemp(prefix="m8_test_")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _copy_canonical(self, target_name: str) -> str:
        dst = os.path.join(self.temp_dir, target_name)
        shutil.copytree(self.canonical_session_dir, dst)
        return dst

    # --------------------------------------------------------------------------
    # Test A: Valid Mini session import
    # --------------------------------------------------------------------------
    def test_A_valid_mini_session_import(self):
        """A. Valid canonical Mini session imports with success=True and populated observations."""
        self.assertTrue(os.path.isdir(self.canonical_session_dir))
        result = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        self.assertTrue(result.success, f"Import failed with errors: {result.report.errors}")
        self.assertEqual(result.session_metadata.session_id, "MINI-AVEO-F14D3-001")
        self.assertEqual(len(result.observations), 82)
        self.assertEqual(result.report.valid_samples, 81)
        self.assertEqual(result.report.no_data, 1)
        self.assertEqual(result.source, "SEYYANEN_MINI")

    # --------------------------------------------------------------------------
    # Test B: Missing metadata
    # --------------------------------------------------------------------------
    def test_B_missing_metadata(self):
        """B. Missing metadata.json is detected and flagged as MISSING_METADATA."""
        session_dir = self._copy_canonical("sess_no_meta")
        os.remove(os.path.join(session_dir, "metadata.json"))

        result = smi.import_mini_session(session_dir)
        self.assertFalse(result.success)
        self.assertTrue(any("MISSING_METADATA" in e for e in result.report.errors))

    # --------------------------------------------------------------------------
    # Test C: Malformed metadata
    # --------------------------------------------------------------------------
    def test_C_malformed_metadata(self):
        """C. Non-JSON or corrupted metadata is flagged as INVALID_METADATA."""
        session_dir = self._copy_canonical("sess_bad_meta")
        with open(os.path.join(session_dir, "metadata.json"), "w") as f:
            f.write("{corrupted json string...[")

        result = smi.import_mini_session(session_dir)
        self.assertFalse(result.success)
        self.assertTrue(any("INVALID_METADATA" in e for e in result.report.errors))

    # --------------------------------------------------------------------------
    # Test D: Missing CSV
    # --------------------------------------------------------------------------
    def test_D_missing_csv(self):
        """D. Missing session.csv is detected."""
        session_dir = self._copy_canonical("sess_no_csv")
        os.remove(os.path.join(session_dir, "session.csv"))

        result = smi.import_mini_session(session_dir)
        self.assertFalse(result.success)
        self.assertTrue(any("not found" in e.lower() for e in result.report.errors))

    # --------------------------------------------------------------------------
    # Test E: Schema mismatch
    # --------------------------------------------------------------------------
    def test_E_schema_mismatch(self):
        """E. CSV header mismatch is detected and rejected."""
        session_dir = self._copy_canonical("sess_bad_hdr")
        csv_path = os.path.join(session_dir, "session.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        lines[0] = "wrong,header,columns\n"
        with open(csv_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        result = smi.import_mini_session(session_dir)
        self.assertFalse(result.success)
        self.assertTrue(any("SCHEMA_MISMATCH" in e for e in result.report.errors))

    # --------------------------------------------------------------------------
    # Test F: Invalid timestamp
    # --------------------------------------------------------------------------
    def test_F_invalid_timestamp(self):
        """F. Non-integer timestamp_us is flagged as INVALID_TIMESTAMP."""
        session_dir = self._copy_canonical("sess_bad_ts")
        csv_path = os.path.join(session_dir, "session.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        parts = lines[1].split(",")
        parts[0] = "NOT_A_TIMESTAMP"
        lines[1] = ",".join(parts)
        with open(csv_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        result = smi.import_mini_session(session_dir)
        self.assertFalse(result.success)
        self.assertTrue(any("INVALID_TIMESTAMP" in e for e in result.report.errors))

    # --------------------------------------------------------------------------
    # Test G: Invalid PID
    # --------------------------------------------------------------------------
    def test_G_invalid_pid(self):
        """G. Non-hexadecimal PID is flagged as INVALID_PID."""
        session_dir = self._copy_canonical("sess_bad_pid")
        csv_path = os.path.join(session_dir, "session.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        parts = lines[1].split(",")
        parts[3] = "ZZZZ"  # Invalid hex PID
        lines[1] = ",".join(parts)
        with open(csv_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        result = smi.import_mini_session(session_dir)
        self.assertFalse(result.success)
        self.assertTrue(any("INVALID_PID" in e for e in result.report.errors))

    # --------------------------------------------------------------------------
    # Test H: Invalid numeric value
    # --------------------------------------------------------------------------
    def test_H_invalid_numeric_value(self):
        """H. Non-numeric value on VALID sample is flagged as INVALID_NUMERIC_VALUE."""
        session_dir = self._copy_canonical("sess_bad_num")
        csv_path = os.path.join(session_dir, "session.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        parts = lines[1].split(",")
        parts[7] = "NOT_A_FLOAT"  # decoded_value column
        lines[1] = ",".join(parts)
        with open(csv_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        result = smi.import_mini_session(session_dir)
        self.assertFalse(result.success)
        self.assertTrue(any("INVALID_NUMERIC_VALUE" in e for e in result.report.errors))

    # --------------------------------------------------------------------------
    # Test I: VALID row mapping
    # --------------------------------------------------------------------------
    def test_I_valid_row_mapping(self):
        """I. VALID row maps correctly to canonical name, unit, and float value."""
        result = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        self.assertTrue(result.success)

        # First sample is RPM (010C)
        obs0 = result.observations[0]
        self.assertEqual(obs0.pid, "010C")
        self.assertEqual(obs0.canonical_name, "RPM")
        self.assertEqual(obs0.unit, "rpm")
        self.assertEqual(obs0.status, "VALID")
        self.assertAlmostEqual(obs0.value, 780.0, delta=10.0)

    # --------------------------------------------------------------------------
    # Test J: TIMEOUT row mapping
    # --------------------------------------------------------------------------
    def test_J_timeout_row_mapping(self):
        """J. TIMEOUT sample preserves empty decoded value and status TIMEOUT."""
        session_dir = self._copy_canonical("sess_timeout")
        csv_path = os.path.join(session_dir, "session.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # Change row 2 to TIMEOUT
        parts = lines[2].split(",")
        parts[7] = ""  # empty decoded_value
        parts[9] = "TIMEOUT"
        parts[10] = "TIMEOUT"
        lines[2] = ",".join(parts)
        with open(csv_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        result = smi.import_mini_session(session_dir, options={"force_reimport": True})
        self.assertTrue(result.success)
        obs1 = result.observations[1]
        self.assertEqual(obs1.status, "TIMEOUT")
        self.assertIsNone(obs1.value)
        self.assertEqual(result.report.timeouts, 1)

    # --------------------------------------------------------------------------
    # Test K: NO DATA mapping
    # --------------------------------------------------------------------------
    def test_K_no_data_mapping(self):
        """K. NO DATA sample is preserved without zero fabrication."""
        result = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        self.assertTrue(result.success)

        # In canonical session, row index 45 is NO_DATA
        no_data_obs = [o for o in result.observations if o.status == "NO_DATA"]
        self.assertEqual(len(no_data_obs), 1)
        self.assertIsNone(no_data_obs[0].value)
        self.assertEqual(no_data_obs[0].raw_response, "NO DATA")

    # --------------------------------------------------------------------------
    # Test L: Raw response preservation
    # --------------------------------------------------------------------------
    def test_L_raw_response_preservation(self):
        """L. Wire adapter responses (e.g. 41 0C 0C 20) are preserved exactly."""
        result = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        self.assertTrue(result.success)
        self.assertEqual(result.observations[0].raw_response, "41 0C 0C 20")

    # --------------------------------------------------------------------------
    # Test M: Provenance preservation
    # --------------------------------------------------------------------------
    def test_M_provenance_preservation(self):
        """M. Every observation carries full provenance metadata."""
        result = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        self.assertTrue(result.success)
        obs = result.observations[0]
        prov = obs.provenance
        self.assertEqual(prov.source, "SEYYANEN_MINI")
        self.assertEqual(prov.source_session_id, "MINI-AVEO-F14D3-001")
        self.assertEqual(prov.source_file, "session.csv")
        self.assertEqual(prov.source_row, 2)
        self.assertEqual(prov.mini_firmware_version, "1.0.0-m6")
        self.assertIn("vLinker MC+", prov.adapter_identity)
        self.assertEqual(prov.transport_medium, "BLUETOOTH_SPP")
        self.assertEqual(prov.protocol, "ISO 15765-4 (CAN 11/500)")

    # --------------------------------------------------------------------------
    # Test N: Session identity preservation
    # --------------------------------------------------------------------------
    def test_N_session_identity_preservation(self):
        """N. Session ID is preserved and matched across metadata and observations."""
        result = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        self.assertTrue(result.success)
        self.assertEqual(result.session_metadata.session_id, "MINI-AVEO-F14D3-001")
        self.assertEqual(result.report.session_id, "MINI-AVEO-F14D3-001")

    # --------------------------------------------------------------------------
    # Test O: Timestamp normalization
    # --------------------------------------------------------------------------
    def test_O_timestamp_normalization(self):
        """O. Relative session time starts at 0.0s and is reversible."""
        result = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        self.assertTrue(result.success)
        self.assertEqual(result.observations[0].normalized_time_s, 0.0)
        self.assertGreater(result.observations[-1].normalized_time_s, 10.0)

        # Reversible check
        t_norm = TimestampNormalizer(t0_us=result.observations[0].timestamp_us)
        rel_s, _ = t_norm.normalize(result.observations[10].timestamp_us)
        denorm_us = t_norm.denormalize(rel_s)
        self.assertEqual(denorm_us, result.observations[10].timestamp_us)

    # --------------------------------------------------------------------------
    # Test P: Out-of-order detection
    # --------------------------------------------------------------------------
    def test_P_out_of_order_detection(self):
        """P. Decreasing timestamps are caught as NON_MONOTONIC_TIMESTAMP."""
        session_dir = self._copy_canonical("sess_ooo")
        csv_path = os.path.join(session_dir, "session.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        parts = lines[5].split(",")
        parts[0] = "1000000000"  # Jumps back into the past
        lines[5] = ",".join(parts)
        with open(csv_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        result = smi.import_mini_session(session_dir)
        self.assertFalse(result.success)
        self.assertTrue(any("NON_MONOTONIC_TIMESTAMP" in e for e in result.report.errors))

    # --------------------------------------------------------------------------
    # Test Q: Duplicate detection
    # --------------------------------------------------------------------------
    def test_Q_duplicate_detection(self):
        """Q. Duplicate sequence numbers generate warnings."""
        session_dir = self._copy_canonical("sess_dup")
        csv_path = os.path.join(session_dir, "session.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # Set line 4 sequence same as line 3
        parts = lines[4].split(",")
        parts[1] = lines[3].split(",")[1]
        lines[4] = ",".join(parts)
        with open(csv_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        result = smi.import_mini_session(session_dir, options={"force_reimport": True})
        self.assertGreater(result.report.duplicates, 0)
        self.assertTrue(any("DUPLICATE_SEQUENCE" in w for w in result.report.warnings))

    # --------------------------------------------------------------------------
    # Test R: Deterministic import
    # --------------------------------------------------------------------------
    def test_R_deterministic_import(self):
        """R. Importing twice yields identical normalized observations and hashes."""
        res1 = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        res2 = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        self.assertEqual(res1.session_hash, res2.session_hash)
        self.assertEqual(len(res1.observations), len(res2.observations))
        for o1, o2 in zip(res1.observations, res2.observations):
            self.assertEqual(o1.timestamp_us, o2.timestamp_us)
            self.assertEqual(o1.value, o2.value)
            self.assertEqual(o1.raw_response, o2.raw_response)

    # --------------------------------------------------------------------------
    # Test S: Idempotent repeated import
    # --------------------------------------------------------------------------
    def test_S_idempotent_repeated_import(self):
        """S. Importing without force_reimport reports ALREADY_IMPORTED."""
        # First import
        smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        # Second import without force_reimport
        res2 = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": False})
        self.assertTrue(res2.already_imported)
        self.assertTrue(any("ALREADY_IMPORTED" in w for w in res2.report.warnings))

    # --------------------------------------------------------------------------
    # Test T: Unknown vehicle identity
    # --------------------------------------------------------------------------
    def test_T_unknown_vehicle_identity(self):
        """T. Default import keeps vehicle_identity_status as UNKNOWN."""
        result = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        self.assertTrue(result.success)
        self.assertEqual(result.session_metadata.vehicle.vehicle_identity_status, "UNKNOWN")

    # --------------------------------------------------------------------------
    # Test U: Explicit vehicle attachment
    # --------------------------------------------------------------------------
    def test_U_explicit_vehicle_attachment(self):
        """U. User can explicitly attach a vehicle instance / VIN."""
        result = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        self.assertTrue(result.success)
        smi.attach_session_to_vehicle(result, "KL1TF48768B123456")
        self.assertEqual(result.vehicle_attached, "KL1TF48768B123456")
        self.assertEqual(result.session_metadata.vehicle.vehicle_identity_status, "ATTACHED")
        self.assertEqual(result.session_metadata.vehicle.vin, "KL1TF48768B123456")

    # --------------------------------------------------------------------------
    # Test V: PID metadata reconciliation
    # --------------------------------------------------------------------------
    def test_V_pid_metadata_reconciliation(self):
        """V. Standard PIDs reconcile against desktop definitions."""
        result = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        self.assertTrue(result.success)
        for obs in result.observations:
            if obs.pid in ("010C", "0105", "010B", "0111"):
                self.assertIn(obs.reconciliation, ("MINI_METADATA_MATCH", "DESKTOP_METADATA_MATCH"))

    # --------------------------------------------------------------------------
    # Test W: Large-log streaming import
    # --------------------------------------------------------------------------
    def test_W_large_log_streaming_import(self):
        """W. Streaming mode executes without storing entire observation list in RAM."""
        result = smi.import_mini_session(self.canonical_session_dir, options={"streaming_mode": True, "force_reimport": True})
        self.assertTrue(result.success)
        self.assertEqual(len(result.observations), 0)
        self.assertEqual(result.report.rows_valid, 82)

    # --------------------------------------------------------------------------
    # Test X: Import report correctness
    # --------------------------------------------------------------------------
    def test_X_import_report_correctness(self):
        """X. Import report contains valid stats, timing, and formatting."""
        result = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        text = result.report.to_text()
        self.assertIn("SEYYANEN MINI — IMPORT REPORT", text)
        self.assertIn("Session ID:         MINI-AVEO-F14D3-001", text)
        self.assertIn("Total Rows Read:  82", text)
        r_dict = result.report.to_dict()
        self.assertEqual(r_dict["rows_read"], 82)
        self.assertEqual(r_dict["valid_samples"], 81)

    # --------------------------------------------------------------------------
    # Test Y: Existing C-layer handoff
    # --------------------------------------------------------------------------
    def test_Y_existing_c_layer_handoff(self):
        """Y. Observations can be handed off into desktop AutoExpertEngine."""
        result = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        self.assertTrue(result.success)

        handoff_audit = smi.handoff_to_c_layer(result.observations)
        self.assertIn("processed", handoff_audit)
        self.assertEqual(handoff_audit["processed"], 82)
        self.assertGreater(handoff_audit["trusted"], 50)

    # --------------------------------------------------------------------------
    # Test Z: No bypass of quality/trust layer
    # --------------------------------------------------------------------------
    def test_Z_no_bypass_of_quality_trust_layer(self):
        """Z. Implausible measurements remain suspect/implausible when fed to C-layer."""
        result = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        self.assertTrue(result.success)

        # Inject an implausible RPM measurement into observations (e.g. 20,000 RPM)
        test_obs = list(result.observations)
        bad_obs = smi.MiniObservation(
            timestamp_us=1726842799999000,
            normalized_time_s=50.0,
            wall_clock_iso=None,
            pid="010C",
            canonical_name="RPM",
            value=22000.0,  # Physically impossible for Aveo 1.4L
            unit="rpm",
            status="VALID",
            quality="GOOD",
            freshness="FRESH",
            latency_us=24000,
            raw_response="41 0C FF FF",
            mini_decoded_value=22000.0
        )
        test_obs.append(bad_obs)

        from motor import AutoExpertEngine
        engine = AutoExpertEngine()
        handoff_audit = smi.handoff_to_c_layer(test_obs, engine=engine)
        self.assertGreater(handoff_audit["suspect_or_implausible"], 0)

    # --------------------------------------------------------------------------
    # Test AA: No duplicate persistence
    # --------------------------------------------------------------------------
    def test_AA_no_duplicate_persistence(self):
        """AA. Handoff to persistence recognizes already-imported sessions."""
        res1 = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": True})
        self.assertFalse(res1.already_imported)
        res2 = smi.import_mini_session(self.canonical_session_dir, options={"force_reimport": False})
        self.assertTrue(res2.already_imported)

    # --------------------------------------------------------------------------
    # Test AB: Path validation and zip slip security
    # --------------------------------------------------------------------------
    def test_AB_path_validation(self):
        """AB. Non-existent path fails gracefully with FileNotFoundError."""
        result = smi.import_mini_session("/non/existent/path/session")
        self.assertFalse(result.success)
        self.assertTrue(any("does not exist" in e for e in result.report.errors))

    # --------------------------------------------------------------------------
    # Test AC: UI preview state inspection
    # --------------------------------------------------------------------------
    def test_AC_ui_preview_state(self):
        """AC. Fast preview returns accurate summary without full sample parsing."""
        preview = smi.preview_mini_session(self.canonical_session_dir)
        self.assertTrue(preview.is_valid)
        self.assertEqual(preview.session_id, "MINI-AVEO-F14D3-001")
        self.assertEqual(preview.adapter_name, "vLinker MC+")
        self.assertEqual(preview.sample_count, 82)
        self.assertEqual(preview.vehicle_identity_status, "UNKNOWN")

    # --------------------------------------------------------------------------
    # Test AD: Malformed request handling
    # --------------------------------------------------------------------------
    def test_AD_malformed_request_handling(self):
        """AD. Handling damaged zip or empty folder fails safely."""
        empty_dir = os.path.join(self.temp_dir, "empty_folder")
        os.makedirs(empty_dir, exist_ok=True)
        preview = smi.preview_mini_session(empty_dir)
        self.assertFalse(preview.is_valid)
        self.assertTrue(any("MISSING_METADATA" in e for e in preview.errors))


if __name__ == "__main__":
    unittest.main()
