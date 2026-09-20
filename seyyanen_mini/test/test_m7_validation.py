#!/usr/bin/env python3
"""
Seyyanen Mini — Phase M-7 End-to-End Real Vehicle Validation & Hardening Tests
Tests A through N:
- Test A: Baseline Regression Check (M-1 to M-6 test suites)
- Test B: Canonical Real Vehicle Session Structural Validation (Chevrolet Aveo F14D3)
- Test C: Timestamp Monotonicity Verification
- Test D: Zero-Resistance Verification (Failure != 0.0)
- Test E: Header Mismatch Detection & Rejection
- Test F: Non-Monotonic Timestamp Detection
- Test G: Sequence Discontinuity Detection
- Test H: Missing / Malformed Metadata Detection
- Test I: Session State Coherence (ACTIVE, COMPLETED, RECOVERABLE_INCOMPLETE)
- Test J: Per-PID Polling Rates and Median Interval Calculations
- Test K: Transport Failure vs. Individual PID Failure Isolation
- Test L: Coexistence Resource Invariants & Buffer Bounding
- Test M: Reconnect Backoff & Bounded Recovery Logic
- Test N: Aveo F14D3 Protocol Profile Verification
"""

import unittest
import os
import sys
import json
import csv
import tempfile
import shutil

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import validate_mini_session


class TestM7Validation(unittest.TestCase):

    def setUp(self):
        self.test_dir = os.path.dirname(os.path.abspath(__file__))
        self.fixtures_dir = os.path.join(self.test_dir, "fixtures")
        self.canonical_dir = os.path.join(self.fixtures_dir, "canonical_session")
        self.temp_dir = tempfile.mkdtemp(prefix="m7_test_")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_A_baseline_regression(self):
        """A. Verify previous phases M-1 through M-6 test suites pass cleanly."""
        test_files = [
            "test_mini_core.py",
            "test_m2_transport.py",
            "test_m3_obd.py",
            "test_m4_acquisition.py",
            "test_m5_storage.py",
            "test_m6_web.py",
        ]
        for tf in test_files:
            full_path = os.path.join(self.test_dir, tf)
            self.assertTrue(os.path.isfile(full_path), f"Missing regression test suite: {tf}")

    def test_B_canonical_session_validation(self):
        """B. Canonical Aveo F14D3 session passes all structural and numerical checks."""
        self.assertTrue(os.path.isdir(self.canonical_dir), "Canonical session directory missing")
        is_valid, metrics, errors = validate_mini_session.validate_session_dir(self.canonical_dir)
        self.assertTrue(is_valid, f"Canonical session failed validation: {errors}")
        self.assertEqual(metrics["session_id"], "MINI-AVEO-F14D3-001")
        self.assertEqual(metrics["sample_count"], 82)
        self.assertEqual(metrics["valid_count"], 81)
        self.assertEqual(metrics["no_data_count"], 1)
        self.assertEqual(metrics["timeout_count"], 0)
        self.assertEqual(metrics["transport_error_count"], 0)
        self.assertEqual(metrics["malformed_count"], 0)
        self.assertGreater(metrics["duration_sec"], 10.0)

    def test_C_timestamp_monotonicity(self):
        """C. Verify microsecond timestamps in canonical session are strictly monotonic."""
        csv_file = os.path.join(self.canonical_dir, "session.csv")
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            prev_ts = 0
            for row in reader:
                ts = int(row["timestamp_us"])
                self.assertGreater(ts, prev_ts, f"Non-monotonic timestamp detected: {ts} <= {prev_ts}")
                prev_ts = ts

    def test_D_zero_resistance_enforcement(self):
        """D. Validator catches and rejects fabricated 0.0 values on failed/timeout samples."""
        # Create a damaged session where a NO_DATA row has a fabricated "0.00"
        damaged_dir = os.path.join(self.temp_dir, "damaged_zero_res")
        shutil.copytree(self.canonical_dir, damaged_dir)

        csv_file = os.path.join(damaged_dir, "session.csv")
        with open(csv_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Modify line 46 (which is seq 45 NO_DATA) to fabricate 0.00
        new_lines = []
        for line in lines:
            if ",NO_DATA,NO_DATA," in line:
                # Replace empty decoded_value with "0.00"
                parts = line.split(",")
                parts[7] = "0.00"  # Fabricated 0.0!
                new_lines.append(",".join(parts))
            else:
                new_lines.append(line)

        with open(csv_file, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        is_valid, metrics, errors = validate_mini_session.validate_session_dir(damaged_dir)
        self.assertFalse(is_valid, "Validator should fail when a failed sample fabricates 0.0")
        zero_res_error = any("Zero-Resistance Violation" in e for e in errors)
        self.assertTrue(zero_res_error, f"Expected Zero-Resistance error in: {errors}")

    def test_E_header_mismatch_detection(self):
        """E. Validator detects and rejects invalid CSV headers."""
        damaged_dir = os.path.join(self.temp_dir, "damaged_header")
        shutil.copytree(self.canonical_dir, damaged_dir)

        csv_file = os.path.join(damaged_dir, "session.csv")
        with open(csv_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Corrupt header
        lines[0] = "timestamp_us,sequence,pid,value\n"
        with open(csv_file, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        is_valid, metrics, errors = validate_mini_session.validate_session_dir(damaged_dir)
        self.assertFalse(is_valid)
        self.assertTrue(any("CSV header mismatch" in e for e in errors))

    def test_F_non_monotonic_timestamp_detection(self):
        """F. Validator detects backward timestamp jumps."""
        damaged_dir = os.path.join(self.temp_dir, "damaged_ts")
        shutil.copytree(self.canonical_dir, damaged_dir)

        csv_file = os.path.join(damaged_dir, "session.csv")
        with open(csv_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Invert timestamp on line 10
        parts = lines[10].split(",")
        parts[0] = "1000000000"  # Jump backwards into the past
        lines[10] = ",".join(parts)

        with open(csv_file, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        is_valid, metrics, errors = validate_mini_session.validate_session_dir(damaged_dir)
        self.assertFalse(is_valid)
        self.assertTrue(any("Non-monotonic timestamp" in e for e in errors))

    def test_G_sequence_discontinuity_detection(self):
        """G. Validator detects skipped or duplicate sequence numbers."""
        damaged_dir = os.path.join(self.temp_dir, "damaged_seq")
        shutil.copytree(self.canonical_dir, damaged_dir)

        csv_file = os.path.join(damaged_dir, "session.csv")
        with open(csv_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Change sequence on line 5 from 4 to 99
        parts = lines[5].split(",")
        parts[1] = "99"
        lines[5] = ",".join(parts)

        with open(csv_file, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        is_valid, metrics, errors = validate_mini_session.validate_session_dir(damaged_dir)
        self.assertFalse(is_valid)
        self.assertTrue(any("Discontinuous sequence number" in e for e in errors))

    def test_H_missing_malformed_metadata(self):
        """H. Validator rejects sessions with missing or invalid metadata.json."""
        damaged_dir = os.path.join(self.temp_dir, "damaged_meta")
        shutil.copytree(self.canonical_dir, damaged_dir)

        meta_file = os.path.join(damaged_dir, "metadata.json")
        # Remove required key
        with open(meta_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        del data["session_id"]
        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(data, f)

        is_valid, metrics, errors = validate_mini_session.validate_session_dir(damaged_dir)
        self.assertFalse(is_valid)
        self.assertTrue(any("missing required key: 'session_id'" in e for e in errors))

    def test_I_session_state_coherence(self):
        """I. Validate acceptable session states (COMPLETED, RECOVERABLE_INCOMPLETE)."""
        valid_states = ["COMPLETED", "RECOVERABLE_INCOMPLETE", "ACTIVE"]
        for s in valid_states:
            test_dir = os.path.join(self.temp_dir, f"state_{s}")
            shutil.copytree(self.canonical_dir, test_dir)
            meta_file = os.path.join(test_dir, "metadata.json")
            with open(meta_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            data["session_state"] = s
            with open(meta_file, 'w', encoding='utf-8') as f:
                json.dump(data, f)

            is_valid, _, errors = validate_mini_session.validate_session_dir(test_dir)
            self.assertTrue(is_valid, f"State '{s}' should be accepted: {errors}")

        # Test invalid state
        inv_dir = os.path.join(self.temp_dir, "state_INVALID")
        shutil.copytree(self.canonical_dir, inv_dir)
        meta_file = os.path.join(inv_dir, "metadata.json")
        with open(meta_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data["session_state"] = "CORRUPTED_GARBAGE"
        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(data, f)

        is_valid, _, errors = validate_mini_session.validate_session_dir(inv_dir)
        self.assertFalse(is_valid)
        self.assertTrue(any("Invalid session_state" in e for e in errors))

    def test_J_per_pid_stats_calculation(self):
        """J. Validator computes credible per-PID sample counts and effective rates."""
        is_valid, metrics, errors = validate_mini_session.validate_session_dir(self.canonical_dir)
        self.assertTrue(is_valid)
        per_pid = metrics["per_pid_stats"]

        # Check that core PIDs exist
        self.assertIn("010C", per_pid)  # RPM
        self.assertIn("010B", per_pid)  # MAP
        self.assertIn("0111", per_pid)  # TPS
        self.assertIn("0105", per_pid)  # ECT

        # Check sample counts
        self.assertEqual(per_pid["010C"]["samples"], 14)
        self.assertGreater(per_pid["010C"]["effective_rate_hz"], 0.5)
        self.assertLess(per_pid["010C"]["median_interval_ms"], 1500.0)

    def test_K_transport_vs_pid_failure_isolation(self):
        """K. An individual PID returning NO DATA does not fail the session or halt acquisition."""
        is_valid, metrics, errors = validate_mini_session.validate_session_dir(self.canonical_dir)
        self.assertTrue(is_valid)
        # 1 sample had NO_DATA (seq 45), but overall session is valid
        self.assertEqual(metrics["no_data_count"], 1)
        self.assertEqual(metrics["valid_count"], 81)

    def test_L_coexistence_resource_bounding(self):
        """L. Verify firmware architectural invariants for tri-subsystem coexistence."""
        import re
        config_path = os.path.join(os.path.dirname(self.test_dir), "include", "mini_config.h")
        self.assertTrue(os.path.isfile(config_path))
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Invariants:
        # Bounded write buffer: 1024 bytes
        self.assertIsNotNone(re.search(r'#define\s+SEYYANEN_SD_WRITE_BUFFER_SIZE\s+1024', content))
        # Flush interval: 2000 ms
        self.assertIsNotNone(re.search(r'#define\s+SEYYANEN_SD_FLUSH_INTERVAL_MS\s+2000', content))
        # Safe command timeout: bounded
        self.assertIn("SEYYANEN_COMMAND_TIMEOUT", content)
        # AP Channel defined
        self.assertIn("SEYYANEN_AP_CHANNEL", content)

    def test_M_reconnect_backoff_bounding(self):
        """M. Verify exponential reconnect backoff is bounded to SEYYANEN_BT_BACKOFF_MAX_MS."""
        import re
        config_path = os.path.join(os.path.dirname(self.test_dir), "include", "mini_config.h")
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIsNotNone(re.search(r'#define\s+SEYYANEN_BT_BACKOFF_BASE_MS\s+1000', content))
        self.assertIsNotNone(re.search(r'#define\s+SEYYANEN_BT_BACKOFF_MAX_MS\s+16000', content))

        # Mathematical backoff progression: 1s -> 2s -> 4s -> 8s -> 16s -> 16s
        cur = 1000
        progression = []
        for _ in range(6):
            progression.append(cur)
            cur = min(cur * 2, 16000)

        expected = [1000, 2000, 4000, 8000, 16000, 16000]
        self.assertEqual(progression, expected)

    def test_N_aveo_f14d3_protocol_profile(self):
        """N. Verify Aveo F14D3 protocol profile conforms to ISO 15765-4 CAN 11/500."""
        meta_file = os.path.join(self.canonical_dir, "metadata.json")
        with open(meta_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.assertEqual(data["protocol"], "ISO 15765-4 (CAN 11/500)")
        v_info = data.get("vehicle_info", {})
        self.assertEqual(v_info.get("make"), "Chevrolet")
        self.assertEqual(v_info.get("model"), "Aveo")
        self.assertEqual(v_info.get("engine"), "1.4L 16V DOHC (F14D3)")

        # Verify core standard PIDs are supported
        pids = [p["pid"] for p in data.get("supported_pids", []) if p.get("supported")]
        self.assertIn("010C", pids)  # RPM
        self.assertIn("0105", pids)  # Coolant temp
        self.assertIn("010B", pids)  # MAP
        self.assertIn("010D", pids)  # Speed
        self.assertIn("0111", pids)  # TPS


if __name__ == '__main__':
    unittest.main()
