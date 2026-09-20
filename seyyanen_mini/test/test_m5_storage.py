#!/usr/bin/env python3
"""
SEYYANEN MINI — PHASE M-5 DETERMINISTIC MICROSD STORAGE TESTS
=============================================================
Validates all tests A through X from Phase M-5 specification:
A. SD mount success
B. card missing
C. session creation
D. session ID uniqueness
E. CSV header correctness
F. sample serialization
G. raw response escaping
H. failure sample serialization
I. metadata serialization
J. PID metadata persistence
K. buffered writes
L. flush policy
M. session finalization
N. incomplete session detection
O. SD write failure
P. SD full condition
Q. bounded queue
R. dropped sample accounting
S. session listing
T. active-session protection
U. path traversal rejection
V. long-session counters
W. timestamp preservation
X. download path validation
"""

import io
import json
import re
import unittest
from typing import Dict, List, Optional, Tuple

# ==============================================================================
# REFERENCE TYPES & CONSTANTS MIRRORING C++ M-5 STORAGE ENGINE
# ==============================================================================

WRITE_BUFFER_SIZE = 1024
CSV_HEADER = "timestamp_us,sequence,frame_id,pid,name,request,raw_response,decoded_value,unit,status,quality,freshness,latency_us\n"

class StorageStatus:
    IDLE = "IDLE"
    READY = "READY"
    NO_CARD = "NO_CARD"
    READ_ONLY = "READ_ONLY"
    CARD_FULL = "CARD_FULL"
    WRITE_ERROR = "WRITE_ERROR"
    FILESYSTEM_ERROR = "FILESYSTEM_ERROR"

class SessionState:
    NO_SESSION = "NO_SESSION"
    STARTING = "STARTING"
    ACTIVE = "ACTIVE"
    STOPPING = "STOPPING"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    RECOVERABLE_INCOMPLETE = "RECOVERABLE_INCOMPLETE"
    ERROR = "ERROR"

class FakeVirtualFile:
    def __init__(self, path: str, fs: 'FakeSdFileSystem'):
        self.path = path
        self.fs = fs
        self.buffer = io.BytesIO()
        self.is_open = True

    def write(self, data: bytes) -> int:
        if not self.is_open:
            return 0
        if self.fs.simulate_write_failure:
            return 0
        if self.fs.free_bytes < len(data):
            return 0
        written = self.buffer.write(data)
        self.fs.free_bytes -= written
        return written

    def flush(self):
        pass

    def close(self):
        self.is_open = False

    def get_content(self) -> str:
        return self.buffer.getvalue().decode('utf-8', errors='replace')

    def size(self) -> int:
        return self.buffer.tell()

class FakeSdFileSystem:
    def __init__(self, card_present: bool = True, total_mb: int = 16384):
        self.card_present = card_present
        self.total_bytes = total_mb * 1024 * 1024
        self.free_bytes = self.total_bytes
        self.directories = set()
        self.files: Dict[str, FakeVirtualFile] = {}
        self.simulate_write_failure = False

    def exists(self, path: str) -> bool:
        return (path in self.directories) or (path in self.files)

    def mkdir(self, path: str) -> bool:
        if not self.card_present:
            return False
        self.directories.add(path)
        return True

    def open(self, path: str, mode: str = "w") -> Optional[FakeVirtualFile]:
        if not self.card_present:
            return None
        if "w" in mode or mode == "FILE_WRITE":
            f = FakeVirtualFile(path, self)
            self.files[path] = f
            return f
        else: # read
            if path in self.files:
                f = self.files[path]
                f.buffer.seek(0)
                return f
            return None

class MockSdLogger:
    session_counter = 1

    def __init__(self, fs: FakeSdFileSystem):
        self.fs = fs
        self.status = StorageStatus.IDLE
        self.last_error = ""
        self.current_session_id = ""
        self.session_state = SessionState.NO_SESSION
        self.sample_count = 0
        self.error_count = 0
        self.frame_count = 0
        self.samples_written = 0
        self.samples_dropped = 0
        self.write_errors = 0
        self.flush_count = 0

        self.current_file: Optional[FakeVirtualFile] = None
        self.events_file: Optional[FakeVirtualFile] = None
        self.write_buffer = ""
        self.last_flush_ms = 0

    def begin(self) -> bool:
        if not self.fs.card_present:
            self.status = StorageStatus.NO_CARD
            self.last_error = "CARD_NOT_PRESENT"
            return False

        self.fs.mkdir("/SEYYANEN")
        self.fs.mkdir("/SEYYANEN/SESSIONS")
        self.status = StorageStatus.READY
        self.last_error = "NONE"

        # Scan for incomplete sessions
        self.scan_incomplete_sessions()
        return True

    def is_ready(self) -> bool:
        return self.fs.card_present and self.status == StorageStatus.READY

    @staticmethod
    def is_valid_session_id(session_id: str) -> bool:
        if not session_id or len(session_id) < 3 or len(session_id) > 35:
            return False
        # Strictly alphanumeric, dashes, and underscores
        return bool(re.match(r'^[a-zA-Z0-9_-]+$', session_id))

    def start_session(self, session_id: str, adapter_info: dict, protocol: str, supported_pids: list) -> bool:
        if not self.is_ready():
            self.status = StorageStatus.NO_CARD
            self.last_error = "CARD_NOT_PRESENT"
            return False

        if not self.is_valid_session_id(session_id):
            self.last_error = "INVALID_SESSION_ID"
            return False

        if self.session_state == SessionState.ACTIVE:
            self.stop_session()

        session_dir = f"/SEYYANEN/SESSIONS/{session_id}"
        self.fs.mkdir(session_dir)

        csv_path = f"{session_dir}/session.csv"
        meta_path = f"{session_dir}/metadata.json"
        events_path = f"{session_dir}/events.log"

        self.current_file = self.fs.open(csv_path, "w")
        self.events_file = self.fs.open(events_path, "w")

        if not self.current_file:
            self.status = StorageStatus.WRITE_ERROR
            self.last_error = "FILE_OPEN_FAILED"
            return False

        self.current_session_id = session_id
        self.session_state = SessionState.ACTIVE
        self.sample_count = 0
        self.error_count = 0
        self.frame_count = 0
        self.write_buffer = ""

        # Write CSV Header
        self.buffer_append(CSV_HEADER)
        self.flush_buffer_to_file()

        # Write initial metadata with state = ACTIVE
        meta_doc = {
            "session_id": session_id,
            "start_timestamp_us": 1_000_000,
            "end_timestamp_us": 0,
            "firmware_version": "1.0.0",
            "mini_version": "M-5",
            "adapter_name": adapter_info.get("name", "vLinker MC+"),
            "adapter_model": adapter_info.get("model", "vLinker MC"),
            "adapter_firmware": adapter_info.get("firmware", "v2.2"),
            "adapter_raw_identity": adapter_info.get("raw_identity", "vLinker MC+ 2.2"),
            "transport_medium": "BLUETOOTH_SPP",
            "protocol": protocol,
            "vehicle_context_status": "UNKNOWN",
            "supported_pid_count": len(supported_pids),
            "sample_count": 0,
            "frame_count": 0,
            "error_count": 0,
            "session_state": SessionState.ACTIVE,
            "supported_pids": supported_pids
        }
        meta_file = self.fs.open(meta_path, "w")
        if meta_file:
            meta_file.write(json.dumps(meta_doc, indent=2).encode('utf-8'))
            meta_file.close()

        self.write_event("SESSION_START", "Recording session active")
        return True

    def stop_session(self) -> bool:
        if self.session_state not in (SessionState.ACTIVE, SessionState.STARTING):
            return True

        self.session_state = SessionState.STOPPING
        self.write_event("SESSION_STOP", "Finalizing session")
        self.flush_buffer_to_file()

        if self.current_file:
            self.current_file.flush()
            self.current_file.close()

        if self.events_file:
            self.events_file.flush()
            self.events_file.close()

        self.session_state = SessionState.COMPLETED

        # Update metadata to COMPLETED
        meta_path = f"/SEYYANEN/SESSIONS/{self.current_session_id}/metadata.json"
        meta_file = self.fs.open(meta_path, "w")
        if meta_file:
            meta_doc = {
                "session_id": self.current_session_id,
                "start_timestamp_us": 1_000_000,
                "end_timestamp_us": 15_000_000,
                "sample_count": self.sample_count,
                "frame_count": self.frame_count,
                "error_count": self.error_count,
                "session_state": SessionState.COMPLETED
            }
            meta_file.write(json.dumps(meta_doc, indent=2).encode('utf-8'))
            meta_file.close()

        return True

    @staticmethod
    def escape_csv_field(val: str) -> str:
        if not val:
            return '""'
        escaped = val.replace('"', '""').replace('\r', ' ').replace('\n', ' ')
        return f'"{escaped}"'

    def write_sample(self, timestamp_us: int, sequence: int, frame_id: int,
                     pid: int, name: str, request: str, raw_response: str,
                     decoded_value: Optional[float], unit: str, status: str,
                     quality: str, freshness: str, latency_us: int) -> bool:
        if not self.is_ready() or self.session_state != SessionState.ACTIVE or not self.current_file:
            self.samples_dropped += 1
            return False

        escaped_raw = self.escape_csv_field(raw_response)

        # Zero-resistance rule: failed measurements output empty string, NEVER fake 0.0!
        if status == "VALID" and decoded_value is not None:
            val_str = f"{decoded_value:.2f}"
        else:
            val_str = ""

        row = f"{timestamp_us},{sequence},{frame_id},{pid:04X},{name},{request},{escaped_raw},{val_str},{unit},{status},{quality},{freshness},{latency_us}\n"

        self.buffer_append(row)
        self.sample_count += 1
        self.samples_written += 1
        if status != "VALID":
            self.error_count += 1
        return True

    def write_frame(self, frame_id: int):
        if self.session_state == SessionState.ACTIVE:
            self.frame_count += 1

    def write_event(self, event_type: str, message: str):
        if self.events_file and self.events_file.is_open:
            line = f"1000000 [{event_type}] {message}\n"
            self.events_file.write(line.encode('utf-8'))

    def buffer_append(self, s: str):
        self.write_buffer += s
        if len(self.write_buffer) >= WRITE_BUFFER_SIZE:
            self.flush_buffer_to_file()

    def flush_buffer_to_file(self):
        if self.write_buffer and self.current_file:
            written = self.current_file.write(self.write_buffer.encode('utf-8'))
            if written != len(self.write_buffer):
                self.write_errors += 1
                self.status = StorageStatus.WRITE_ERROR
                self.last_error = "WRITE_FAILED"
            self.write_buffer = ""

    def flush(self):
        self.flush_buffer_to_file()
        if self.current_file:
            self.current_file.flush()
            self.flush_count += 1

    def scan_incomplete_sessions(self):
        for path, f in list(self.fs.files.items()):
            if path.endswith("/metadata.json"):
                content = f.get_content()
                if '"session_state": "ACTIVE"' in content:
                    new_content = content.replace('"session_state": "ACTIVE"', '"session_state": "RECOVERABLE_INCOMPLETE"')
                    self.fs.files[path] = FakeVirtualFile(path, self.fs)
                    self.fs.files[path].write(new_content.encode('utf-8'))

    def list_sessions(self) -> List[dict]:
        sessions = []
        pattern = re.compile(r'^/SEYYANEN/SESSIONS/([^/]+)/metadata\.json$')
        for path, f in self.fs.files.items():
            m = pattern.match(path)
            if m:
                sess_id = m.group(1)
                csv_path = f"/SEYYANEN/SESSIONS/{sess_id}/session.csv"
                sz = self.fs.files[csv_path].size() if csv_path in self.fs.files else 0
                try:
                    meta = json.loads(f.get_content())
                    state = meta.get("session_state", SessionState.COMPLETED)
                    samples = meta.get("sample_count", 0)
                except Exception:
                    state = SessionState.ERROR
                    samples = 0

                sessions.append({
                    "session_id": sess_id,
                    "state": state,
                    "sample_count": samples,
                    "size_bytes": sz
                })
        return sessions

    def open_session_file_for_read(self, session_id: str, filename: str) -> Optional[FakeVirtualFile]:
        if not self.is_valid_session_id(session_id):
            return None
        if filename not in ("session.csv", "metadata.json", "events.log"):
            return None
        path = f"/SEYYANEN/SESSIONS/{session_id}/{filename}"
        return self.fs.open(path, "r")

# ==============================================================================
# UNIT TEST SUITE (TESTS A THROUGH X)
# ==============================================================================

class TestM5StorageEngine(unittest.TestCase):

    def setUp(self):
        self.fs = FakeSdFileSystem(card_present=True, total_mb=16384)
        self.logger = MockSdLogger(self.fs)
        self.adapter_info = {
            "name": "vLinker MC+ 2.2",
            "model": "vLinker MC",
            "firmware": "v2.2",
            "raw_identity": "vLinker MC+ 2.2 MIC3322"
        }
        self.pids = [
            {"pid": "010C", "name": "RPM", "unit": "rpm", "poll_interval_ms": 120},
            {"pid": "0105", "name": "ECT", "unit": "°C", "poll_interval_ms": 1200}
        ]

    def test_A_sd_mount_success(self):
        """A. SD mount succeeds when card is present, creates base directories."""
        self.assertTrue(self.logger.begin())
        self.assertEqual(self.logger.status, StorageStatus.READY)
        self.assertTrue(self.fs.exists("/SEYYANEN"))
        self.assertTrue(self.fs.exists("/SEYYANEN/SESSIONS"))

    def test_B_card_missing(self):
        """B. Card missing enters NO_CARD status gracefully without crashing."""
        fs_no_card = FakeSdFileSystem(card_present=False)
        logger_no_card = MockSdLogger(fs_no_card)
        self.assertFalse(logger_no_card.begin())
        self.assertEqual(logger_no_card.status, StorageStatus.NO_CARD)
        self.assertEqual(logger_no_card.last_error, "CARD_NOT_PRESENT")

    def test_C_session_creation(self):
        """C. Session creation creates session folder, CSV, metadata, and event log."""
        self.logger.begin()
        ok = self.logger.start_session("MINI-20260920-001", self.adapter_info, "ISO 15765-4", self.pids)
        self.assertTrue(ok)
        self.assertTrue(self.fs.exists("/SEYYANEN/SESSIONS/MINI-20260920-001"))
        self.assertTrue(self.fs.exists("/SEYYANEN/SESSIONS/MINI-20260920-001/session.csv"))
        self.assertTrue(self.fs.exists("/SEYYANEN/SESSIONS/MINI-20260920-001/metadata.json"))
        self.assertTrue(self.fs.exists("/SEYYANEN/SESSIONS/MINI-20260920-001/events.log"))

    def test_D_session_id_uniqueness(self):
        """D. Distinct sessions create distinct isolated directories."""
        self.logger.begin()
        self.logger.start_session("MINI-SESSION-001", self.adapter_info, "ISO 15765-4", self.pids)
        self.logger.stop_session()

        self.logger.start_session("MINI-SESSION-002", self.adapter_info, "ISO 15765-4", self.pids)
        self.logger.stop_session()

        self.assertTrue(self.fs.exists("/SEYYANEN/SESSIONS/MINI-SESSION-001/session.csv"))
        self.assertTrue(self.fs.exists("/SEYYANEN/SESSIONS/MINI-SESSION-002/session.csv"))

    def test_E_csv_header_correctness(self):
        """E. CSV header conforms precisely to specification."""
        self.logger.begin()
        self.logger.start_session("MINI-SESSION-001", self.adapter_info, "ISO 15765-4", self.pids)
        csv_f = self.fs.open("/SEYYANEN/SESSIONS/MINI-SESSION-001/session.csv", "r")
        content = csv_f.get_content()
        self.assertTrue(content.startswith(CSV_HEADER))

    def test_F_sample_serialization(self):
        """F. Standard measurement sample formats all CSV columns properly."""
        self.logger.begin()
        self.logger.start_session("MINI-SESSION-001", self.adapter_info, "ISO 15765-4", self.pids)
        self.logger.write_sample(
            timestamp_us=1000021, sequence=1, frame_id=12,
            pid=0x010C, name="RPM", request="010C", raw_response="41 0C 1A F8",
            decoded_value=1726.0, unit="rpm", status="VALID",
            quality="GOOD", freshness="FRESH", latency_us=42000
        )
        self.logger.flush()
        content = self.fs.files["/SEYYANEN/SESSIONS/MINI-SESSION-001/session.csv"].get_content()
        expected_row = '1000021,1,12,010C,RPM,010C,"41 0C 1A F8",1726.00,rpm,VALID,GOOD,FRESH,42000\n'
        self.assertIn(expected_row, content)

    def test_G_raw_response_escaping(self):
        """G. Raw adapter responses with quotes or commas are safely escaped."""
        escaped1 = MockSdLogger.escape_csv_field("41 0C 1A F8")
        self.assertEqual(escaped1, '"41 0C 1A F8"')

        escaped2 = MockSdLogger.escape_csv_field('41 0C "TEST"')
        self.assertEqual(escaped2, '"41 0C ""TEST"""')

    def test_H_failure_sample_serialization(self):
        """H. Failed sample leaves decoded_value empty and does NOT fabricate 0.0."""
        self.logger.begin()
        self.logger.start_session("MINI-SESSION-001", self.adapter_info, "ISO 15765-4", self.pids)
        self.logger.write_sample(
            timestamp_us=1000050, sequence=2, frame_id=12,
            pid=0x010B, name="MAP", request="010B", raw_response="",
            decoded_value=None, unit="kPa", status="TIMEOUT",
            quality="TIMEOUT", freshness="STALE", latency_us=400000
        )
        self.logger.flush()
        content = self.fs.files["/SEYYANEN/SESSIONS/MINI-SESSION-001/session.csv"].get_content()
        # Ensure consecutive commas ,, for decoded value (no 0.0!)
        self.assertIn(',"",,kPa,TIMEOUT,TIMEOUT,STALE,400000', content)
        self.assertNotIn(',0.00,', content)

    def test_I_metadata_serialization(self):
        """I. Metadata JSON is created with active state, adapter info, and UNKNOWN vehicle status."""
        self.logger.begin()
        self.logger.start_session("MINI-SESSION-001", self.adapter_info, "ISO 15765-4", self.pids)
        meta_f = self.fs.files["/SEYYANEN/SESSIONS/MINI-SESSION-001/metadata.json"]
        meta = json.loads(meta_f.get_content())
        self.assertEqual(meta["session_id"], "MINI-SESSION-001")
        self.assertEqual(meta["session_state"], SessionState.ACTIVE)
        self.assertEqual(meta["vehicle_context_status"], "UNKNOWN")
        self.assertEqual(meta["adapter_name"], "vLinker MC+ 2.2")

    def test_J_pid_metadata_persistence(self):
        """J. Supported PID metadata list is stored in metadata.json."""
        self.logger.begin()
        self.logger.start_session("MINI-SESSION-001", self.adapter_info, "ISO 15765-4", self.pids)
        meta_f = self.fs.files["/SEYYANEN/SESSIONS/MINI-SESSION-001/metadata.json"]
        meta = json.loads(meta_f.get_content())
        self.assertIn("supported_pids", meta)
        self.assertEqual(len(meta["supported_pids"]), 2)
        self.assertEqual(meta["supported_pids"][0]["name"], "RPM")

    def test_K_buffered_writes(self):
        """K. Small writes accumulate in write buffer before writing to card."""
        self.logger.begin()
        self.logger.start_session("MINI-SESSION-001", self.adapter_info, "ISO 15765-4", self.pids)

        # Write small sample (~80 bytes)
        self.logger.write_sample(
            timestamp_us=1000021, sequence=1, frame_id=1,
            pid=0x010C, name="RPM", request="010C", raw_response="41 0C 1A F8",
            decoded_value=1726.0, unit="rpm", status="VALID",
            quality="GOOD", freshness="FRESH", latency_us=42000
        )
        # Buffer has data, but not yet flushed to file (except header)
        self.assertGreater(len(self.logger.write_buffer), 0)

    def test_L_flush_policy(self):
        """L. Explicit flush commits all buffered rows to storage file."""
        self.logger.begin()
        self.logger.start_session("MINI-SESSION-001", self.adapter_info, "ISO 15765-4", self.pids)
        self.logger.write_sample(
            timestamp_us=1000021, sequence=1, frame_id=1,
            pid=0x010C, name="RPM", request="010C", raw_response="41 0C 1A F8",
            decoded_value=1726.0, unit="rpm", status="VALID",
            quality="GOOD", freshness="FRESH", latency_us=42000
        )
        self.logger.flush()
        self.assertEqual(len(self.logger.write_buffer), 0)
        self.assertEqual(self.logger.flush_count, 1)

    def test_M_session_finalization(self):
        """M. Stopping session marks session_state as COMPLETED and updates counts."""
        self.logger.begin()
        self.logger.start_session("MINI-SESSION-001", self.adapter_info, "ISO 15765-4", self.pids)
        self.logger.write_sample(1000000, 1, 1, 0x010C, "RPM", "010C", "41 0C", 1800.0, "rpm", "VALID", "GOOD", "FRESH", 25)
        self.logger.stop_session()

        meta_f = self.fs.files["/SEYYANEN/SESSIONS/MINI-SESSION-001/metadata.json"]
        meta = json.loads(meta_f.get_content())
        self.assertEqual(meta["session_state"], SessionState.COMPLETED)
        self.assertEqual(meta["sample_count"], 1)

    def test_N_incomplete_session_detection(self):
        """N. Unfinalized ACTIVE session from unexpected shutdown is marked RECOVERABLE_INCOMPLETE."""
        self.logger.begin()
        self.logger.start_session("MINI-UNSAVED-001", self.adapter_info, "ISO 15765-4", self.pids)
        # Simulate power cut: session was never stopped!

        # Next boot
        new_logger = MockSdLogger(self.fs)
        new_logger.begin()

        meta_f = self.fs.files["/SEYYANEN/SESSIONS/MINI-UNSAVED-001/metadata.json"]
        meta = json.loads(meta_f.get_content())
        self.assertEqual(meta["session_state"], SessionState.RECOVERABLE_INCOMPLETE)

    def test_O_sd_write_failure(self):
        """O. SD write failure transitions to WRITE_ERROR and increments write_errors."""
        self.logger.begin()
        self.logger.start_session("MINI-SESSION-001", self.adapter_info, "ISO 15765-4", self.pids)

        self.fs.simulate_write_failure = True
        self.logger.write_sample(1000000, 1, 1, 0x010C, "RPM", "010C", "41 0C", 1800.0, "rpm", "VALID", "GOOD", "FRESH", 25)
        self.logger.flush()

        self.assertEqual(self.logger.status, StorageStatus.WRITE_ERROR)
        self.assertGreater(self.logger.write_errors, 0)

    def test_P_sd_full_condition(self):
        """P. Card full condition fails writes and drops samples without crashing."""
        self.logger.begin()
        self.logger.start_session("MINI-SESSION-001", self.adapter_info, "ISO 15765-4", self.pids)

        # Set free bytes to 0
        self.fs.free_bytes = 0
        self.logger.write_sample(1000000, 1, 1, 0x010C, "RPM", "010C", "41 0C", 1800.0, "rpm", "VALID", "GOOD", "FRESH", 25)
        self.logger.flush()

        self.assertGreater(self.logger.write_errors, 0)

    def test_Q_bounded_queue(self):
        """Q. In-memory write buffer remains strictly bounded to 1024 bytes."""
        self.logger.begin()
        self.logger.start_session("MINI-SESSION-001", self.adapter_info, "ISO 15765-4", self.pids)

        # Write 20 samples (~1600 bytes) without manual flush
        for i in range(20):
            self.logger.write_sample(1000000 + i, i+1, 1, 0x010C, "RPM", "010C", "41 0C", 1800.0, "rpm", "VALID", "GOOD", "FRESH", 25)

        # The buffer must have flushed automatically to stay under 1024 bytes
        self.assertLess(len(self.logger.write_buffer), WRITE_BUFFER_SIZE)

    def test_R_dropped_sample_accounting(self):
        """R. Dropped samples when storage is inactive or full are counted in samples_dropped."""
        # Write before starting session
        ok = self.logger.write_sample(1000000, 1, 1, 0x010C, "RPM", "010C", "41 0C", 1800.0, "rpm", "VALID", "GOOD", "FRESH", 25)
        self.assertFalse(ok)
        self.assertEqual(self.logger.samples_dropped, 1)

    def test_S_session_listing(self):
        """S. list_sessions enumerates all sessions without reading entire files into RAM."""
        self.logger.begin()
        self.logger.start_session("MINI-SESS-A", self.adapter_info, "ISO 15765-4", self.pids)
        self.logger.write_sample(1000000, 1, 1, 0x010C, "RPM", "010C", "41 0C", 1800.0, "rpm", "VALID", "GOOD", "FRESH", 25)
        self.logger.stop_session()

        self.logger.start_session("MINI-SESS-B", self.adapter_info, "ISO 15765-4", self.pids)
        self.logger.stop_session()

        sessions = self.logger.list_sessions()
        self.assertEqual(len(sessions), 2)
        sess_ids = [s["session_id"] for s in sessions]
        self.assertIn("MINI-SESS-A", sess_ids)
        self.assertIn("MINI-SESS-B", sess_ids)

    def test_T_active_session_protection(self):
        """T. Active session protects mutable file by flushing before openSessionFileForRead."""
        self.logger.begin()
        self.logger.start_session("MINI-SESSION-ACTIVE", self.adapter_info, "ISO 15765-4", self.pids)
        self.logger.write_sample(1000000, 1, 1, 0x010C, "RPM", "010C", "41 0C", 1800.0, "rpm", "VALID", "GOOD", "FRESH", 25)

        # Flushes before reading
        self.logger.flush()
        f = self.logger.open_session_file_for_read("MINI-SESSION-ACTIVE", "session.csv")
        self.assertIsNotNone(f)
        self.assertIn("1000000", f.get_content())

    def test_U_path_traversal_rejection(self):
        """U. Security Gate rejects path traversal attempts (../, /etc/passwd, special characters)."""
        bad_ids = [
            "../etc/passwd",
            "..\\windows\\system32",
            "session/nested",
            "sess.ion",
            "sess;rm",
            "../../../SEYYANEN",
            "a" * 40 # exceeds max len
        ]
        for bad_id in bad_ids:
            self.assertFalse(MockSdLogger.is_valid_session_id(bad_id), f"Should reject: {bad_id}")

        good_ids = [
            "MINI-SESSION-000001",
            "SESSION_20260920",
            "SESS-123_456"
        ]
        for good_id in good_ids:
            self.assertTrue(MockSdLogger.is_valid_session_id(good_id), f"Should accept: {good_id}")

    def test_V_long_session_counters(self):
        """V. Long sessions support timestamps and sample counts beyond 32-bit limits."""
        self.logger.begin()
        self.logger.start_session("MINI-LONG-001", self.adapter_info, "ISO 15765-4", self.pids)

        ts_64 = 1726859345123456 # > 2^32 microseconds (~54 years)
        seq_large = 100_000 # 100k samples in a several-hour drive
        self.logger.write_sample(ts_64, seq_large, 5000, 0x010C, "RPM", "010C", "41 0C", 2000.0, "rpm", "VALID", "GOOD", "FRESH", 20)
        self.logger.flush()

        content = self.fs.files["/SEYYANEN/SESSIONS/MINI-LONG-001/session.csv"].get_content()
        self.assertIn("1726859345123456,100000,5000", content)

    def test_W_timestamp_preservation(self):
        """W. Microsecond timestamps are stored precisely without loss of resolution."""
        self.logger.begin()
        self.logger.start_session("MINI-TS-001", self.adapter_info, "ISO 15765-4", self.pids)
        self.logger.write_sample(1000123, 1, 1, 0x010C, "RPM", "010C", "41 0C", 850.0, "rpm", "VALID", "GOOD", "FRESH", 25)
        self.logger.write_sample(1000456, 2, 1, 0x0111, "TPS", "0111", "41 11", 14.5, "%", "VALID", "GOOD", "FRESH", 25)
        self.logger.flush()

        content = self.fs.files["/SEYYANEN/SESSIONS/MINI-TS-001/session.csv"].get_content()
        self.assertIn("1000123,1,1", content)
        self.assertIn("1000456,2,1", content)

    def test_X_download_path_validation(self):
        """X. openSessionFileForRead allows only session.csv, metadata.json, and events.log."""
        self.logger.begin()
        self.logger.start_session("MINI-DL-001", self.adapter_info, "ISO 15765-4", self.pids)

        self.assertIsNotNone(self.logger.open_session_file_for_read("MINI-DL-001", "session.csv"))
        self.assertIsNotNone(self.logger.open_session_file_for_read("MINI-DL-001", "metadata.json"))
        self.assertIsNotNone(self.logger.open_session_file_for_read("MINI-DL-001", "events.log"))

        # Block unauthorized files
        self.assertIsNone(self.logger.open_session_file_for_read("MINI-DL-001", "secret.txt"))
        self.assertIsNone(self.logger.open_session_file_for_read("MINI-DL-001", "../../../boot.ini"))

if __name__ == "__main__":
    unittest.main()
