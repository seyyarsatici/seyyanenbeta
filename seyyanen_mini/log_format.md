# SEYYANEN MINI — LOG FORMAT & IMPORT SPECIFICATION (PHASE M-5)

This specification defines the storage layout, CSV schema, metadata structure, and desktop import contract for sessions recorded by **Seyyanen Mini (ESP32)**.

---

## 1. Directory Structure

Sessions are persisted on the MicroSD card under a root managed directory:

```text
/SEYYANEN/
└── SESSIONS/
    ├── MINI-20260920-223411-001/
    │   ├── session.csv          # Primary time-series measurements
    │   ├── metadata.json        # Session context, adapter info, PID table, state
    │   └── events.log           # Diagnostic lifecycle event stream
    ├── MINI-20260920-231502-002/
    │   ├── session.csv
    │   ├── metadata.json
    │   └── events.log
    └── ...
```

---

## 2. Measurement Data (`session.csv`)

### Header Row:
```csv
timestamp_us,sequence,frame_id,pid,name,request,raw_response,decoded_value,unit,status,quality,freshness,latency_us
```

### Field Definitions:

| Column | Type | Example | Description |
| :--- | :--- | :--- | :--- |
| `timestamp_us` | uint64 | `1000021` | Monotonic microsecond timestamp from ESP32 monotonic clock. Primary temporal ordering key. |
| `sequence` | uint32 | `1` | Monotonically increasing sample sequence within the session. Resets to 1 per session. |
| `frame_id` | uint32 | `12` | Monotonic acquisition cycle index (groups non-simultaneous readings into temporal cycles). |
| `pid` | string (hex) | `010C` | Standard OBD-II Mode 01 PID code (4 hex characters). |
| `name` | string | `RPM` | Human-readable parameter name / short code. |
| `request` | string (hex) | `010C` | Exact command transmitted on the wire. |
| `raw_response` | string | `"41 0C 1A F8"` | Exact raw response string received from the adapter (double-quoted, internal quotes escaped). |
| `decoded_value`| float / null | `1726.00` | Decoded numeric value in standard engineering units. **EMPTY on failed/timed-out requests**. |
| `unit` | string | `rpm` | Engineering unit of measurement (e.g. `rpm`, `kPa`, `°C`, `%`). |
| `status` | string | `VALID` | Technical sample status: `VALID`, `TIMEOUT`, `NO_DATA`, `MALFORMED`, `TRANSPORT_ERROR`. |
| `quality` | string | `GOOD` | Quality grade: `GOOD`, `DEGRADED`, `STALE`, `TIMEOUT`, `NO_DATA`, `MALFORMED`, `TRANSPORT_ERROR`. |
| `freshness` | string | `FRESH` | Freshness decay state: `FRESH`, `AGING`, `STALE`, `NEVER_VALID`. |
| `latency_us` | uint32 | `42000` | Round-trip request-to-response duration in microseconds. |

### Valid Sample Example:
```csv
1000021,1,12,010C,RPM,010C,"41 0C 1A F8",1726.00,rpm,VALID,GOOD,FRESH,42000
1000065,2,12,010B,MAP,010B,"41 0B 32",50.00,kPa,VALID,GOOD,FRESH,38000
```

### Failed Sample Example (Failure $\ne$ Zero):
> [!IMPORTANT]
> If a query times out or returns `NO DATA`, `decoded_value` is **strictly empty** (consecutive commas `,,`). Zero is **never** fabricated.
```csv
1000115,3,12,0105,ECT,0105,"",,"°C",TIMEOUT,TIMEOUT,STALE,400000
```

---

## 3. Session Context (`metadata.json`)

Stored in the session folder to provide provenance, adapter identification, and supported PID configuration:

```json
{
  "session_id": "MINI-20260920-223411-001",
  "start_timestamp_us": 1000000,
  "end_timestamp_us": 18500000,
  "start_wall_time": "2026-09-20T22:34:11Z",
  "end_wall_time": "2026-09-20T22:34:28Z",
  "firmware_version": "1.0.0",
  "mini_version": "M-5",
  "adapter_name": "vLinker MC+ 2.2",
  "adapter_model": "vLinker MC",
  "adapter_firmware": "v2.2",
  "adapter_raw_identity": "vLinker MC+ 2.2 MIC3322",
  "transport_medium": "BLUETOOTH_SPP",
  "protocol": "ISO 15765-4 (CAN 11/500)",
  "vehicle_context_status": "UNKNOWN",
  "supported_pid_count": 8,
  "sample_count": 142,
  "frame_count": 18,
  "error_count": 2,
  "session_state": "COMPLETED",
  "supported_pids": [
    {
      "pid": "010C",
      "name": "Engine RPM",
      "short_code": "RPM",
      "unit": "rpm",
      "decoder": "DECODER_RPM",
      "poll_interval_ms": 120,
      "priority": 0,
      "supported": true
    },
    {
      "pid": "010B",
      "name": "Intake Manifold Pressure",
      "short_code": "MAP",
      "unit": "kPa",
      "decoder": "DECODER_MAP",
      "poll_interval_ms": 350,
      "priority": 1,
      "supported": true
    }
  ]
}
```

### Power-Loss & Recovery Indicator (`session_state`):
- `ACTIVE`: Session is currently being recorded.
- `COMPLETED`: Session was cleanly closed via `stopSession()`.
- `RECOVERABLE_INCOMPLETE`: Power cut or unexpected reboot occurred during recording. The CSV file up to the last flush is intact and recoverable.

---

## 4. Diagnostic Event Log (`events.log`)

A chronological sequence of discrete diagnostic and lifecycle events:
```text
1000000 [SESSION_START] Recording session active
1000100 [PID_SCAN_COMPLETE] Discovered 8 supported PIDs
5200000 [ACQUISITION_PAUSED] Scheduler paused
7400000 [ACQUISITION_RESUMED] Scheduler resumed
18500000 [SESSION_STOP] Finalizing session
```

---

## 5. Desktop Seyyanen Ingestion Pipeline

When PC Seyyanen imports a session directory:
1. **Validate Manifest**:
   - Parse `metadata.json`. Check `session_state`. If `RECOVERABLE_INCOMPLETE`, notify the user that the trailing session records were partially recorded before power cutoff.
2. **Verify Protocol & Provenance**:
   - Check `adapter_raw_identity` and `protocol` to configure expected timing windows.
3. **Parse Time-Series Data (`session.csv`)**:
   - Verify header columns.
   - For each row, check `timestamp_us` for strict monotonicity.
   - Separate trusted values (`status == "VALID"` and `quality == "GOOD"`) from error records (`status == "TIMEOUT"`, etc.).
   - Error records are treated as missing data events for temporal analysis, not zero values.
4. **Feed Desktop Intelligence**:
   - Construct observation vectors and feed into cross-sensor RCA, dynamic reference comparison, and temporal anomaly detectors.
