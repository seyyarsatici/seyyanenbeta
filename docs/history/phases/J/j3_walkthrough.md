# Phase J-3: Data Persistence Walkthrough

## Executive Summary
Phase J-3 introduces a reliable, structured, versioned, and crash-safe persistence layer for the Seyyanen automotive diagnostic platform.

The architectural role of Phase J-3 is:
$$\text{C } \rightarrow \text{ I Diagnostic Intelligence} \xrightarrow{} \text{Domain / Diagnostic Models} \xrightarrow{} \text{Persistence Abstraction (J-3)} \xrightarrow{} \text{Storage Backend (SQLite / In-Memory)}$$

Diagnostic sessions, vehicle contexts, multi-ECU contexts, raw acquisition bytes, findings, evidence, hypotheses, test candidates and results, technician observations, and post-repair verifications can now survive application restarts, crash events, and power loss without coupling higher intelligence layers to database engines, SQL schemas, or filesystem paths.

---

## 1. Persistence Architecture & Domain/Storage Separation

Prior to Phase J-3, the diagnostic platform relied on transient in-memory objects (`DiagnosticWorkflow`, `DiagnosticReasoningSession`, `DiagnosticGraph`, `HistoricalDiagnosticCase`) and temporary flat files (`history.json`, `vehicle_cache.json`). There was no unified, crash-resilient mechanism to persist session lifecycles or audit trails.

Phase J-3 establishes strict architectural boundaries:
- **Diagnostic Intelligence (C $\rightarrow$ I)**: Remains completely agnostic of SQL queries, table names, filesystems, or storage drivers.
- **Domain Models**: Defined as pure dataclasses (`DiagnosticSessionRecord`, `RawAcquisitionRecord`, `DiagnosticWorkflow`, `HistoricalDiagnosticCase`, `DiagnosticReasoningSession`, `DiagnosticGraph`). Domain objects do not inherit from database ORM classes.
- **Persistence Abstraction (`IPersistenceBackend`)**: Decouples storage operations into a standard contract supporting records, raw BLOB payloads, query filtering, pagination, and atomic transactions.
- **Storage Backend**: Embedded `sqlite3` in production with zero external dependencies, integrated with J-2's `PlatformManager.get_app_data_path()`, alongside an ephemeral `InMemoryPersistenceBackend` for ultra-fast, side-effect-free testing.

```
+-------------------------------------------------------------+
|               C -> I Diagnostic Intelligence                |
+-------------------------------------------------------------+
                              |
+-------------------------------------------------------------+
|     Domain Models (Sessions, Workflows, Cases, Graphs)      |
+-------------------------------------------------------------+
                              |
+-------------------------------------------------------------+
|       DiagnosticRepository & PersistenceManager (Facade)     |
|   - save_session / get_session / list_sessions              |
|   - save_workflow / get_workflow                            |
|   - save_historical_case / get_historical_case              |
|   - save_reasoning_session / get_reasoning_session          |
|   - save_diagnostic_graph / get_diagnostic_graph            |
|   - save_raw_acquisition / get_raw_acquisition              |
|   - record_technician_observation / record_repair_verif     |
+-------------------------------------------------------------+
                              |
+-------------------------------------------------------------+
|              IPersistenceBackend (Abstraction)              |
+-------------------------------------------------------------+
               |                               |
+-----------------------------+ +-----------------------------+
|  SQLitePersistenceBackend   | | InMemoryPersistenceBackend  |
|  (ACID Embedded Production) | | (Fast Deterministic Double) |
+-----------------------------+ +-----------------------------+
```

---

## 2. Storage Backend Selection

### Primary Backend: SQLite (`SQLitePersistenceBackend`)
- **Zero External Dependencies**: Uses Python standard library `sqlite3`.
- **Relational Indexing**: Secondary indices on `(collection, vehicle_id)`, `(collection, ecu_id)`, and `(collection, created_at)` enable sub-millisecond lookups.
- **WAL Journaling**: Configured with Write-Ahead Logging (`PRAGMA journal_mode = WAL;`) to support safe concurrent reads without blocking writes.
- **Platform-Aware Location**: Automatically resolves its database path via J-2 `PlatformManager.get_app_data_path("seyyanen_diagnostics.db")`.

### Ephemeral Backend: In-Memory (`InMemoryPersistenceBackend`)
- Provides deep-copy isolated dictionaries for unit testing and ephemeral runtimes.
- Implements transaction snapshots for instantaneous rollback on failure.

---

## 3. Schema Versioning & Forward Migration Strategy

Every persisted record carries an explicit `schema_version` field (currently `1`).

### Migration Pipeline (`SchemaMigrationRegistry`)
- **Forward Migration**: When loading a record with `schema_version < CURRENT_SCHEMA_VERSION`, the registry runs sequential migration transforms from version $v$ to $v+1$.
- **Fail-Closed on Future Versions**: Attempting to load a record with `schema_version > CURRENT_SCHEMA_VERSION` raises `UnsupportedSchemaVersionError`. The system refuses to guess or silently misinterpret unknown future schemas.

---

## 4. Raw vs Derived Data Preservation

The persistence layer preserves bit-for-bit accuracy of raw vehicle telemetry:
- **Raw Acquisition Payloads**: Stored as exact binary BLOBs (`raw_blob`) with microsecond timestamps, command/PID strings, and source ECU identifiers.
- **Derived Findings**: Normalizations, converted physical engineering units (e.g. RPM, fuel trim %), and AI reasoning traces are stored separately in structured JSON.
- **Invariant**: Raw bytes are never overwritten, approximated, or mutated by downstream analytical interpretations.

---

## 5. Current vs Historical Data Separation

The persistence layer maintains an ironclad invariant:
$$\textbf{CURRENT LIVE VEHICLE EVIDENCE } \neq \textbf{ HISTORICAL KNOWLEDGE}$$
- Persisted historical cases (`HistoricalDiagnosticCase`) store confirmed past repairs and archived DTCs.
- When an active live diagnostic session (`DiagnosticSessionRecord`) is opened for the same vehicle, it **never** automatically inherits historical DTCs as active faults.
- Historical data provides contextual evidence for I-4 experience analysis, never active vehicle ground truth.

---

## 6. Multi-Subsystem Integration (H, I, G, J)

| Subsystem | Persisted Entity | Preserved Semantics |
| :--- | :--- | :--- |
| **H-5 Workflow** | `DiagnosticWorkflow` | Stage transitions, policies, test sequences, and technician gates survive application shutdown. |
| **I-4 History** | `HistoricalDiagnosticCase` | Root causes, parts replaced, technician confirmations, and post-repair verifications. |
| **I-5 Reasoning** | `DiagnosticReasoningSession` | Competitor hypotheses, decomposed evidence scores, contradictions, uncertainty, and traces. |
| **G-5 Graph** | `DiagnosticGraph` | Nodes, edges, confidence weights, and the strict invariant: `RELATIONSHIP != CAUSALITY`. |
| **J-1 Hardware** | `AdapterMetadata` | Adapter ID, hardware type, transport medium, and capability flags recorded in session context. |
| **J-2 Platform** | Standard Paths | Database and cache paths resolved dynamically via `PlatformManager`. |

---

## 7. Safety Invariants & Execution Isolation

- **Zero Autonomous Execution on Load**: Restoring a workflow, procedure, or test sequence from persistence is strictly data deserialization. It **never** dispatches OBD/UDS frames, invokes hardware adapters, or changes vehicle ECU state.
- **Safe Deserialization**: Standard `json.loads` and strict dataclass validators are used exclusively. Arbitrary code execution vectors (`pickle`, `yaml.unsafe_load`, `eval`) are prohibited.
- **Strict Error Isolation**: Persistence exceptions (`PersistenceError`, `CorruptedPersistenceDataError`, `StorageBackendError`) are flagged with `is_communication_failure = False` and `is_platform_error = False`. A database error is never misdiagnosed as an ECU failure.

---

## 8. Atomicity, Crash Safety & Boundedness

- **Transactional Rollback**: The `transaction()` context manager ensures that if an error occurs mid-write, the entire operation is rolled back with zero partial writes.
- **Crash Simulation**: Simulated abrupt crashes (`KeyboardInterrupt`, mid-write exceptions) verified that pre-existing valid sessions remain 100% intact.
- **Bounded Pagination**: `list_records` requires explicit limits and offsets, preventing memory exhaustion when querying large session archives.

---

## 9. Comprehensive Test Suite & Results

### Dedicated Suite (`test_phase_j3.py`)
Covers 34 certified dimensions (A through AH):
- **A**: Storage interface compliance (SQLite & InMemory)
- **B**: Create / save / load round-trip
- **C**: In-place record updates
- **D**: Filtered queries and pagination
- **E**: Stable entity ID retention
- **F**: Schema version stamping
- **G**: Schema migration pipeline
- **H**: Future/unknown schema rejection (fail-closed)
- **I**: Malformed data rejection
- **J**: Corrupted JSON handling
- **K**: Atomic multi-record writes
- **L**: Transaction rollback on failure
- **M**: Crash & interrupted write simulation
- **N**: Large dataset behavior (250+ records)
- **O**: Bounded memory & binary BLOB storage
- **P**: Diagnostic session full lifecycle
- **Q**: Vehicle & multi-ECU context preservation
- **R**: Bit-for-bit raw byte payload accuracy
- **S**: Audit provenance preservation
- **T**: DTC records and freeze frames
- **U**: Diagnostic findings and anomalies
- **V**: Competing fault hypotheses
- **W**: Phase H-5 `DiagnosticWorkflow` persistence
- **X**: Phase I-4 `HistoricalDiagnosticCase` persistence
- **Y**: Phase I-5 `DiagnosticReasoningSession` persistence
- **Z**: Phase G-5 `DiagnosticGraph` persistence (`RELATIONSHIP != CAUSALITY`)
- **AA**: Technician manual observations
- **AB**: Repair outcomes & post-repair verification
- **AC**: Current vs historical data separation
- **AD**: Safety: Data loading NEVER executes ECU commands
- **AE**: Unsafe deserialization rejection
- **AF**: J-2 Platform abstraction path integration
- **AG**: J-1 Hardware adapter metadata integration
- **AH**: Full C $\rightarrow$ I diagnostic intelligence regression

### Test Execution Results
```
python -W error -m unittest test_phase_j3.py -v
----------------------------------------------------------------------
Ran 34 tests in 0.631s
OK
```

### Full Cross-Phase Regressions Verified
- `test_phase_j3.py`: **34 passed** (0 warnings under `-W error`)
- `test_phase_j2.py`: **21 passed**
- `test_phase_j1.py`: **21 passed**
- `test_phase_i_final.py`: **31 passed**
- `test_phase_i1.py` through `test_phase_i5.py`: **112 passed**
- `test_phase_h_final.py`: **20 passed**
- `test_phase_h1.py` through `test_phase_h5.py`: **183 passed**
- `test_phase_g_final.py` & `test_phase_g5.py`: **52 passed**
- `test_c_layer_integration.py` & `test_d_layer_hardening.py`: **All passed**

**Total active tests passing across Phases C through J-3: 512+ tests.**

---

## 10. Known Limitations & Truthful Scope Boundaries

1. **Local Embedded Scope**: Persistence is purposely implemented using local SQLite and In-Memory stores. Distributed clustering and remote databases are intentionally excluded.
2. **Out of Scope (Strictly Preserved Boundaries)**:
   - J-4 User & Session Management (Not implemented)
   - J-5 Security & Authorization Policy (Not implemented)
   - J-6 Production Reliability & Packaging (Not implemented)
   - J-Final Release Gate (Not implemented)

---

## Engineering Release Gate Assessment

- [x] Storage abstraction (`IPersistenceBackend`) implemented cleanly.
- [x] SQLite and InMemory backends verified with ACID transactions.
- [x] Schema versioning and forward migration pipeline verified.
- [x] Fail-closed rejection of unknown future schemas and corrupted data.
- [x] Bit-for-bit raw byte acquisition preservation verified.
- [x] Full integration with H-5 workflows, I-4 cases, I-5 reasoning, and G-5 graphs.
- [x] Historical data != current truth invariant verified.
- [x] Loading persisted state never executes commands.
- [x] All 34 tests in `test_phase_j3.py` executed and passing under `-W error`.
- [x] Full cross-phase regressions passing without defects.
