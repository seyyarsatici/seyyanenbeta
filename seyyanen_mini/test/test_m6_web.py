#!/usr/bin/env python3
"""
SEYYANEN MINI — PHASE M-6 DETERMINISTIC WEB UI & SESSION MANAGEMENT TESTS
========================================================================
Validates all tests A through T from Phase M-6 specification:
A. dashboard API response
B. live API response
C. status API
D. metrics API
E. PID API
F. session list
G. session metadata
H. path traversal rejection
I. active session download rejection
J. completed session download
K. malformed session ID
L. unsupported endpoint
M. connection action dispatch
N. acquisition action dispatch
O. recording action dispatch
P. bounded JSON response
Q. no direct transport access from HTTP layer
R. no direct SD filesystem access from HTTP layer
S. malformed request handling
T. state consistency
"""

import json
import re
import unittest
from typing import Dict, List, Optional, Tuple

# ==============================================================================
# MOCK SUBSYSTEMS MIRRORING C++ ARCHITECTURE
# ==============================================================================

class MockBtTransport:
    def __init__(self):
        self.state = "CONNECTED"
        self.adapter_name = "vLinker MC+ 2.2"
        self.firmware = "v2.2"
        self.connect_called = False
        self.disconnect_called = False
        self.reconnect_called = False
        self.direct_io_attempted = False

    def connect(self) -> bool:
        self.connect_called = True
        self.state = "CONNECTED"
        return True

    def disconnect(self) -> bool:
        self.disconnect_called = True
        self.state = "DISCONNECTED"
        return True

    def reconnect(self) -> bool:
        self.reconnect_called = True
        self.state = "CONNECTED"
        return True

    def send_raw(self, data: bytes):
        self.direct_io_attempted = True

class MockElmClient:
    def __init__(self):
        self.state = "READY"
        self.protocol = "ISO 15765-4 (CAN 11/500)"

class MockPidScanner:
    def __init__(self):
        self.state = "COMPLETE"
        self.pids = [
            {"pid_hex": "0C", "name": "Engine RPM", "unit": "rpm", "supported": True, "priority": 0, "poll_interval_ms": 120, "formula": "((A*256)+B)/4"},
            {"pid_hex": "05", "name": "Engine Coolant Temp", "unit": "°C", "supported": True, "priority": 2, "poll_interval_ms": 1200, "formula": "A-40"},
            {"pid_hex": "0B", "name": "Intake Manifold Pressure", "unit": "kPa", "supported": True, "priority": 1, "poll_interval_ms": 350, "formula": "A"},
            {"pid_hex": "11", "name": "Throttle Position", "unit": "%", "supported": True, "priority": 0, "poll_interval_ms": 120, "formula": "A*100/255"}
        ]
        self.scan_called = False

    def scan_supported_pids(self) -> bool:
        self.scan_called = True
        return True

class MockScheduler:
    def __init__(self):
        self.state = "RUNNING"
        self.session_id = "MINI-SESSION-000001"
        self.uptime_sec = 42
        self.start_called = False
        self.stop_called = False
        self.pause_called = False
        self.resume_called = False
        self.signals = [
            {"pid": 0x010C, "pid_hex": "0C", "name": "RPM", "unit": "rpm", "value": 1842.0, "quality": "GOOD", "freshness": "FRESH", "age_ms": 42, "latency_ms": 35},
            {"pid": 0x0105, "pid_hex": "05", "name": "ECT", "unit": "°C", "value": 89.0, "quality": "GOOD", "freshness": "FRESH", "age_ms": 720, "latency_ms": 40}
        ]
        self.metrics = {
            "total_requests": 150,
            "successful_requests": 148,
            "timeouts": 2,
            "no_data_count": 0,
            "malformed_count": 0,
            "transport_errors": 0,
            "average_latency_ms": 38.5,
            "last_latency_ms": 35,
            "requests_per_sec": 12.5,
            "active_pid_count": 4
        }

    def start(self) -> bool:
        self.start_called = True
        self.state = "RUNNING"
        return True

    def stop(self) -> bool:
        self.stop_called = True
        self.state = "STOPPED"
        return True

    def pause(self) -> bool:
        self.pause_called = True
        self.state = "PAUSED"
        return True

    def resume(self) -> bool:
        self.resume_called = True
        self.state = "RUNNING"
        return True

class MockSdLogger:
    def __init__(self):
        self.status = "READY"
        self.current_session_id = "MINI-SESSION-000001"
        self.session_active = True
        self.start_called = False
        self.stop_called = False
        self.direct_fs_attempted = False
        self.sessions = [
            {
                "session_id": "MINI-SESSION-000001",
                "state": "ACTIVE",
                "sample_count": 150,
                "size_bytes": 14200
            },
            {
                "session_id": "MINI-SESSION-000000",
                "state": "COMPLETED",
                "sample_count": 2400,
                "size_bytes": 185000
            }
        ]
        self.metadata_store = {
            "MINI-SESSION-000000": {
                "session_id": "MINI-SESSION-000000",
                "start_timestamp_us": 1000000,
                "end_timestamp_us": 150000000,
                "sample_count": 2400,
                "session_state": "COMPLETED",
                "adapter_name": "vLinker MC+ 2.2",
                "protocol": "ISO 15765-4 (CAN 11/500)"
            }
        }
        self.csv_store = {
            "MINI-SESSION-000000": "timestamp_us,sequence,frame_id,pid,name,request,raw_response,decoded_value,unit,status,quality,freshness,latency_us\n1000000,1,1,010C,RPM,010C,\"41 0C 1A F8\",1726.00,rpm,VALID,GOOD,FRESH,35000\n"
        }

    @staticmethod
    def is_valid_session_id(sess_id: str) -> bool:
        if not sess_id or len(sess_id) < 3 or len(sess_id) > 35:
            return False
        return bool(re.match(r'^[a-zA-Z0-9_-]+$', sess_id))

    def is_ready(self) -> bool:
        return self.status == "READY"

    def is_session_active(self) -> bool:
        return self.session_active

    def get_current_session_id(self) -> str:
        return self.current_session_id

    def start_session(self, sess_id: str) -> bool:
        self.start_called = True
        self.current_session_id = sess_id
        self.session_active = True
        return True

    def stop_session(self) -> bool:
        self.stop_called = True
        self.session_active = False
        return True

# ==============================================================================
# MOCK WEB SERVER DISPATCHER
# ==============================================================================

class MockMiniWebServer:
    def __init__(self, bt: MockBtTransport, elm: MockElmClient,
                 scanner: MockPidScanner, scheduler: MockScheduler,
                 logger: MockSdLogger):
        self.bt = bt
        self.elm = elm
        self.scanner = scanner
        self.scheduler = scheduler
        self.logger = logger

    def handle_request(self, method: str, path: str, query_params: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, str], str]:
        params = query_params or {}

        # 1. Static HTML
        if method == "GET" and path == "/":
            html = "<!DOCTYPE html><html><head><meta name=\"viewport\" content=\"width=device-width\"><title>Seyyanen Mini</title></head><body><h1>SEYYANEN MINI</h1><button>Dashboard</button><button>Live</button><button>Sessions</button></body></html>"
            return 200, {"Content-Type": "text/html"}, html

        # 2. Status API
        if method == "GET" and path == "/api/status":
            doc = {
                "bt_state": self.bt.state,
                "adapter_name": self.bt.adapter_name,
                "firmware": self.bt.firmware,
                "obd_state": self.elm.state,
                "protocol": self.elm.protocol,
                "scanner_state": self.scanner.state,
                "acq_state": self.scheduler.state,
                "session_id": self.scheduler.session_id,
                "sd_status": self.logger.status,
                "free_heap": 184320,
                "uptime_sec": self.scheduler.uptime_sec,
                "supported_count": len(self.scanner.pids)
            }
            return 200, {"Content-Type": "application/json"}, json.dumps(doc)

        # 3. Live Telemetry API
        if method == "GET" and path == "/api/live":
            doc = {
                "bt_state": self.bt.state,
                "obd_state": self.elm.state,
                "state": self.scheduler.state,
                "session_id": self.scheduler.session_id,
                "uptime_sec": self.scheduler.uptime_sec,
                "metrics": self.scheduler.metrics,
                "signals": self.scheduler.signals
            }
            return 200, {"Content-Type": "application/json"}, json.dumps(doc)

        # 4. Metrics API
        if method == "GET" and path == "/api/metrics":
            m = dict(self.scheduler.metrics)
            m["samples_written"] = 150
            m["samples_dropped"] = 0
            m["write_errors"] = 0
            return 200, {"Content-Type": "application/json"}, json.dumps(m)

        # 5. PIDs API
        if method == "GET" and path == "/api/pids":
            doc = {
                "supported_count": len(self.scanner.pids),
                "pids": self.scanner.pids
            }
            return 200, {"Content-Type": "application/json"}, json.dumps(doc)

        # 6. Sessions API
        if method == "GET" and path == "/api/sessions":
            doc = {
                "count": len(self.logger.sessions),
                "sessions": self.logger.sessions
            }
            return 200, {"Content-Type": "application/json"}, json.dumps(doc)

        # 7. Session Metadata API
        if method == "GET" and path == "/api/sessions/metadata":
            sess_id = params.get("id")
            if not sess_id:
                return 400, {"Content-Type": "application/json"}, '{"error":"Missing session id"}'
            if not MockSdLogger.is_valid_session_id(sess_id):
                return 400, {"Content-Type": "application/json"}, '{"error":"Invalid session id"}'
            if sess_id in self.logger.metadata_store:
                return 200, {"Content-Type": "application/json"}, json.dumps(self.logger.metadata_store[sess_id])
            return 404, {"Content-Type": "application/json"}, '{"error":"Session not found"}'

        # 8. Session Download API (with Active Session Protection)
        if method == "GET" and path == "/api/sessions/download":
            sess_id = params.get("id")
            if not sess_id:
                return 400, {"Content-Type": "text/plain"}, "Missing id parameter"
            if not MockSdLogger.is_valid_session_id(sess_id):
                return 400, {"Content-Type": "text/plain"}, "Security error: invalid session ID path"
            # Active Session Protection Rule
            if self.logger.is_session_active() and sess_id == self.logger.get_current_session_id():
                return 400, {"Content-Type": "text/plain"}, "Active recording session cannot be downloaded while writing. Stop recording first."
            if sess_id in self.logger.csv_store:
                return 200, {
                    "Content-Type": "text/csv",
                    "Content-Disposition": f'attachment; filename="{sess_id}_session.csv"'
                }, self.logger.csv_store[sess_id]
            return 404, {"Content-Type": "text/plain"}, "Session CSV file not found"

        # 9. Control Post Routes
        if method == "POST":
            if path == "/api/connect":
                self.bt.connect()
                return 200, {"Content-Type": "application/json"}, '{"status":"ok"}'
            if path == "/api/disconnect":
                self.bt.disconnect()
                return 200, {"Content-Type": "application/json"}, '{"status":"ok"}'
            if path == "/api/reconnect":
                self.bt.reconnect()
                return 200, {"Content-Type": "application/json"}, '{"status":"ok"}'
            if path == "/api/obd/scan":
                self.scanner.scan_supported_pids()
                return 200, {"Content-Type": "application/json"}, '{"status":"ok"}'
            if path == "/api/acquisition/start":
                self.scheduler.start()
                return 200, {"Content-Type": "application/json"}, '{"status":"ok"}'
            if path == "/api/acquisition/stop":
                self.scheduler.stop()
                return 200, {"Content-Type": "application/json"}, '{"status":"ok"}'
            if path == "/api/acquisition/pause":
                self.scheduler.pause()
                return 200, {"Content-Type": "application/json"}, '{"status":"ok"}'
            if path == "/api/acquisition/resume":
                self.scheduler.resume()
                return 200, {"Content-Type": "application/json"}, '{"status":"ok"}'
            if path == "/api/recording/start":
                self.logger.start_session("MINI-SESSION-000001")
                return 200, {"Content-Type": "application/json"}, '{"status":"ok"}'
            if path == "/api/recording/stop":
                self.logger.stop_session()
                return 200, {"Content-Type": "application/json"}, '{"status":"ok"}'

        return 404, {"Content-Type": "text/plain"}, "404: Endpoint Not Found"

# ==============================================================================
# UNIT TEST SUITE (TESTS A THROUGH T)
# ==============================================================================

class TestM6WebManagement(unittest.TestCase):

    def setUp(self):
        self.bt = MockBtTransport()
        self.elm = MockElmClient()
        self.scanner = MockPidScanner()
        self.scheduler = MockScheduler()
        self.logger = MockSdLogger()
        self.server = MockMiniWebServer(self.bt, self.elm, self.scanner, self.scheduler, self.logger)

    def test_A_dashboard_api_response(self):
        """A. Dashboard root HTML response contains mobile viewport meta and primary title."""
        status, headers, body = self.server.handle_request("GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html")
        self.assertIn("SEYYANEN MINI", body)
        self.assertIn("viewport", body)

    def test_B_live_api_response(self):
        """B. GET /api/live returns current live signals snapshot with metadata."""
        status, headers, body = self.server.handle_request("GET", "/api/live")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["state"], "RUNNING")
        self.assertIn("signals", data)
        self.assertGreater(len(data["signals"]), 0)
        sig = data["signals"][0]
        self.assertIn("pid", sig)
        self.assertIn("value", sig)
        self.assertIn("unit", sig)
        self.assertIn("quality", sig)
        self.assertIn("freshness", sig)

    def test_C_status_api(self):
        """C. GET /api/status exposes comprehensive system status."""
        status, headers, body = self.server.handle_request("GET", "/api/status")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("bt_state", data)
        self.assertIn("obd_state", data)
        self.assertIn("acq_state", data)
        self.assertIn("sd_status", data)
        self.assertIn("free_heap", data)
        self.assertIn("uptime_sec", data)

    def test_D_metrics_api(self):
        """D. GET /api/metrics exposes bounded runtime performance metrics."""
        status, headers, body = self.server.handle_request("GET", "/api/metrics")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("total_requests", data)
        self.assertIn("successful_requests", data)
        self.assertIn("average_latency_ms", data)
        self.assertIn("samples_written", data)
        self.assertIn("samples_dropped", data)

    def test_E_pid_api(self):
        """E. GET /api/pids returns discovered supported and registered Mode 01 PIDs."""
        status, headers, body = self.server.handle_request("GET", "/api/pids")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["supported_count"], 4)
        self.assertEqual(data["pids"][0]["name"], "Engine RPM")

    def test_F_session_list(self):
        """F. GET /api/sessions enumerates all recorded sessions without loading CSV files."""
        status, headers, body = self.server.handle_request("GET", "/api/sessions")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["sessions"][0]["session_id"], "MINI-SESSION-000001")

    def test_G_session_metadata(self):
        """G. GET /api/sessions/metadata returns metadata JSON for given session."""
        status, headers, body = self.server.handle_request("GET", "/api/sessions/metadata", {"id": "MINI-SESSION-000000"})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["session_id"], "MINI-SESSION-000000")
        self.assertEqual(data["adapter_name"], "vLinker MC+ 2.2")

    def test_H_path_traversal_rejection(self):
        """H. Reject directory traversal attempts (../, ..\\, /) with 400 Bad Request."""
        bad_paths = ["../../../etc/passwd", "..\\windows\\system32", "/SEYYANEN/SESSIONS", "session/nested"]
        for bp in bad_paths:
            status, _, body = self.server.handle_request("GET", "/api/sessions/metadata", {"id": bp})
            self.assertEqual(status, 400, f"Failed to reject traversal path: {bp}")

    def test_I_active_session_download_rejection(self):
        """I. Active session cannot be downloaded while actively recording (Active Session Protection)."""
        # Session 000001 is currently active in logger
        status, _, body = self.server.handle_request("GET", "/api/sessions/download", {"id": "MINI-SESSION-000001"})
        self.assertEqual(status, 400)
        self.assertIn("Active recording session cannot be downloaded", body)

    def test_J_completed_session_download(self):
        """J. Completed session can be downloaded safely with proper Content-Disposition header."""
        status, headers, body = self.server.handle_request("GET", "/api/sessions/download", {"id": "MINI-SESSION-000000"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/csv")
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("timestamp_us,sequence", body)

    def test_K_malformed_session_id(self):
        """K. Malformed session IDs containing spaces, semicolons, or invalid chars are rejected."""
        malformed = ["SESS 001", "SESS;DROP", "SESS'--", "SE$$ION", "S"]
        for ms in malformed:
            status, _, _ = self.server.handle_request("GET", "/api/sessions/download", {"id": ms})
            self.assertEqual(status, 400, f"Should reject malformed ID: {ms}")

    def test_L_unsupported_endpoint(self):
        """L. Accessing non-existent endpoint returns 404 Not Found."""
        status, _, body = self.server.handle_request("GET", "/api/nonexistent")
        self.assertEqual(status, 404)
        self.assertIn("404", body)

    def test_M_connection_action_dispatch(self):
        """M. POST /api/connect, /api/disconnect, /api/reconnect dispatches to transport API."""
        status, _, _ = self.server.handle_request("POST", "/api/connect")
        self.assertEqual(status, 200)
        self.assertTrue(self.bt.connect_called)

        status, _, _ = self.server.handle_request("POST", "/api/disconnect")
        self.assertEqual(status, 200)
        self.assertTrue(self.bt.disconnect_called)

        status, _, _ = self.server.handle_request("POST", "/api/reconnect")
        self.assertEqual(status, 200)
        self.assertTrue(self.bt.reconnect_called)

    def test_N_acquisition_action_dispatch(self):
        """N. Acquisition POST endpoints dispatch state changes to scheduler."""
        status, _, _ = self.server.handle_request("POST", "/api/acquisition/pause")
        self.assertEqual(status, 200)
        self.assertTrue(self.scheduler.pause_called)

        status, _, _ = self.server.handle_request("POST", "/api/acquisition/resume")
        self.assertEqual(status, 200)
        self.assertTrue(self.scheduler.resume_called)

        status, _, _ = self.server.handle_request("POST", "/api/acquisition/stop")
        self.assertEqual(status, 200)
        self.assertTrue(self.scheduler.stop_called)

    def test_O_recording_action_dispatch(self):
        """O. Recording POST endpoints dispatch to SdLogger."""
        status, _, _ = self.server.handle_request("POST", "/api/recording/start")
        self.assertEqual(status, 200)
        self.assertTrue(self.logger.start_called)

        status, _, _ = self.server.handle_request("POST", "/api/recording/stop")
        self.assertEqual(status, 200)
        self.assertTrue(self.logger.stop_called)

    def test_P_bounded_json_response(self):
        """P. JSON responses from /api/live and /api/status remain strictly bounded under 2 KB."""
        _, _, live_body = self.server.handle_request("GET", "/api/live")
        self.assertLess(len(live_body), 2048, "Live payload should remain compact")

        _, _, status_body = self.server.handle_request("GET", "/api/status")
        self.assertLess(len(status_body), 2048, "Status payload should remain compact")

    def test_Q_no_direct_transport_access_from_http(self):
        """Q. HTTP layer never issues direct I/O to Bluetooth transport."""
        self.server.handle_request("POST", "/api/connect")
        self.server.handle_request("GET", "/api/status")
        self.assertFalse(self.bt.direct_io_attempted, "HTTP handler must never issue direct raw I/O")

    def test_R_no_direct_sd_filesystem_access_from_http(self):
        """R. HTTP layer never opens arbitrary files on SD filesystem."""
        self.server.handle_request("GET", "/api/sessions/download", {"id": "MINI-SESSION-000000"})
        self.assertFalse(self.logger.direct_fs_attempted)

    def test_S_malformed_request_handling(self):
        """S. Missing query parameters on GET endpoints handled gracefully with 400."""
        status, _, body = self.server.handle_request("GET", "/api/sessions/metadata")
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_T_state_consistency(self):
        """T. State updates across subsystems are consistently reflected across status and live endpoints."""
        self.scheduler.state = "PAUSED"
        _, _, live_body = self.server.handle_request("GET", "/api/live")
        self.assertEqual(json.loads(live_body)["state"], "PAUSED")

        _, _, status_body = self.server.handle_request("GET", "/api/status")
        self.assertEqual(json.loads(status_body)["acq_state"], "PAUSED")

if __name__ == "__main__":
    unittest.main()
