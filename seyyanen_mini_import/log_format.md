# SEYYANEN MINI — PC IMPORT SPECIFICATION & LOG FORMAT (PHASE M-8)

## 1. ARCHITECTURAL FLOW

```
ESP32 SEYYANEN MINI (M-5 / M-7)
├── session.csv
├── metadata.json
└── events.log
        │
        ▼ (MicroSD Card or Wi-Fi Download)
HOST PC SEYYANEN
        │
        ▼
[seyyanen_mini_import Package]
├── session_reader.py       (Zip & Directory Resolution, Chunked Streaming)
├── metadata_parser.py      (Session Header, Adapter Identity, Supported PIDs)
├── sample_parser.py        (Streaming CSV Parsing, Zero-Resistance Guard)
├── schema_validator.py     (Classified Validation Errors)
├── timestamp_normalizer.py (Monotonic Reversible Normalization)
├── mini_normalizer.py      (Canonical PID Mapping, Provenance Tagging)
├── import_report.py        (Detailed Metric Accounting)
└── importer.py             (Facade: import, preview, vehicle attachment)
        │
        ▼
[EXISTING SEYYANEN DESKTOP PLATFORM]
├── C-Layer Quality Pipeline (AutoExpertEngine._update_sensor_cache)
├── L-2 Dynamic Reference    (Contextual Plausibility without Baseline Contamination)
├── J-3 Persistence Gateway  (DiagnosticRepository Record & Idempotency)
└── Desktop UI View          (Preview Dialog & Time Series Inspection)
```

---

## 2. SESSION FOLDER LAYOUT

```
SESSION_FOLDER_OR_ZIP/
├── metadata.json    [REQUIRED] - Session metadata, adapter info, PID table
├── session.csv      [REQUIRED] - High-speed time series measurements
└── events.log       [OPTIONAL] - Human-readable lifecycle audit log
```

---

## 3. CSV SCHEMA & ZERO-RESISTANCE RULES

### Header Columns:
```csv
timestamp_us,sequence,frame_id,pid,name,request,raw_response,decoded_value,unit,status,quality,freshness,latency_us
```

| Column | Type | Description |
| :--- | :--- | :--- |
| `timestamp_us` | uint64 | Strictly monotonic hardware microsecond timestamp. |
| `sequence` | uint32 | Contiguous sequence counter starting at 1. |
| `frame_id` | uint32 | Scheduler loop cycle / grouping identifier. |
| `pid` | string | 4-character uppercase hexadecimal Mode 01 PID (e.g. `010C`). |
| `name` | string | Human-readable short mnemonic (e.g. `RPM`). |
| `request` | string | Diagnostic command sent to wire (e.g. `010C`). |
| `raw_response` | string | Exact wire response from adapter, quoted (e.g. `"41 0C 1A F8"`). |
| `decoded_value` | float / empty | Decoded floating-point value. **MUST BE EMPTY on failed requests!** |
| `unit` | string | Standard physical unit (`rpm`, `degC`, `kPa`, `%`, `km/h`, etc.). |
| `status` | string | Execution status: `VALID`, `TIMEOUT`, `NO_DATA`, `TRANSPORT_ERR`, `MALFORMED`, `SAFETY_BLOCKED`. |
| `quality` | string | Diagnostic quality: `GOOD`, `FRESH`, `AGING`, `STALE`, `TIMEOUT`, `NO_DATA`, etc. |
| `freshness` | string | Relative freshness grade (`FRESH`, `AGING`, `STALE`). |
| `latency_us` | uint32 | Round-trip request-to-response duration in microseconds. |

### Zero-Resistance Rule:
- When `status == VALID`, `decoded_value` MUST contain a valid numerical string.
- When `status != VALID` (`TIMEOUT`, `NO_DATA`, `TRANSPORT_ERR`), `decoded_value` **MUST BE COMPLETELY EMPTY** (two consecutive commas `,,`). Fabricating `0.0` or forward-filling historical values is strictly rejected with a `ZERO_RESISTANCE_VIOLATION`.

---

## 4. METADATA SCHEMA (`metadata.json`)

```json
{
  "session_id": "MINI-AVEO-F14D3-001",
  "firmware_version": "1.0.0-m6",
  "mini_protocol_version": "1.0",
  "session_state": "COMPLETED",
  "start_time_iso": "2026-09-20T14:32:00.124Z",
  "end_time_iso": "2026-09-20T14:32:15.892Z",
  "duration_seconds": 15.768,
  "sample_count": 82,
  "frame_count": 14,
  "error_count": 1,
  "adapter_identity": {
    "brand": "VLINKER",
    "adapter_name": "vLinker MC+",
    "manufacturer": "MICROSYS",
    "model": "MC+",
    "firmware": "v2.2",
    "raw_identity": "vLinker MC+ v2.2 MICROSYS",
    "remote_mac": "00:1D:A5:68:98:8B",
    "transport": "BLUETOOTH_SPP",
    "verified": true
  },
  "protocol": "ISO 15765-4 (CAN 11/500)",
  "vehicle_info": {
    "make": "Chevrolet",
    "model": "Aveo",
    "engine": "1.4L 16V DOHC (F14D3)",
    "ecu": "Delphi / Siemens MR-140 / MT58",
    "vin": null,
    "vehicle_identity_status": "UNKNOWN"
  },
  "supported_pids": [
    {
      "pid": "010C",
      "name": "Engine Speed",
      "unit": "rpm",
      "priority": 0,
      "poll_interval_ms": 150,
      "supported": true
    }
  ]
}
```

---

## 5. PROVENANCE & NORMALIZATION TAXONOMY

Every observation imported into Seyyanen carries:
- `source`: `"SEYYANEN_MINI"`
- `source_session_id`: Mini session ID
- `source_file`: `"session.csv"`
- `source_row`: Exact row index in original CSV file
- `mini_firmware_version`: Firmware string
- `adapter_identity`: Adapter make and firmware
- `protocol`: Automotive protocol used during session

### Canonical Desktop PID Reconciliation:
| Mini PID | Desktop Canonical Code | Unit | Reconciliation Status |
| :--- | :--- | :--- | :--- |
| `0104` | `LOAD` | `%` | `MINI_METADATA_MATCH` |
| `0105` | `ECT` | `degC` | `MINI_METADATA_MATCH` |
| `0106` | `STFT1` | `%` | `MINI_METADATA_MATCH` |
| `0107` | `LTFT1` | `%` | `MINI_METADATA_MATCH` |
| `010B` | `MAP` | `kPa` | `MINI_METADATA_MATCH` |
| `010C` | `RPM` | `rpm` | `MINI_METADATA_MATCH` |
| `010D` | `SPEED` | `km/h` | `MINI_METADATA_MATCH` |
| `010E` | `TIMING` | `deg` | `MINI_METADATA_MATCH` |
| `010F` | `IAT` | `degC` | `MINI_METADATA_MATCH` |
| `0110` | `MAF` | `g/s` | `MINI_METADATA_MATCH` |
| `0111` | `TPS` | `%` | `MINI_METADATA_MATCH` |
| Other | Hex PID Code | Mini Unit | `UNKNOWN_PID` |

---

## 6. C-LAYER TRUST HANDOFF INVARIANTS

1. **Evidence vs Trust:** Mini data enters the C-layer as observational evidence. The desktop `AutoExpertEngine` runs its native physical range checks (C-3), temporal jump limits (C-4), and cross-sensor correlations (C-5). Only observations passing all checks enter trusted sensor histories.
2. **Historical Context:** Imported data is stamped with relative session time and labeled as historical evidence. It does not overwrite current live telemetry.
3. **Idempotency:** Re-importing the same session produces an `ALREADY_IMPORTED` notice and avoids duplicate persistent records unless explicitly requested.
