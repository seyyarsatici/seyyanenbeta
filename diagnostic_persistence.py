#!/usr/bin/env python3
"""
Seyyanen Automotive Diagnostic Platform — Phase J-3
===================================================
Data Persistence Architecture
`diagnostic_persistence.py`

Architectural Role:
    C → I Diagnostic Intelligence
        ↓
    Domain / Diagnostic Models (Phases C, D, E, F, G, H, I)
        ↓
    Persistence Abstraction (Phase J-3: diagnostic_persistence.py)
        ↓
    Storage Backend (SQLite / In-Memory / Structured Store)

Strict Architectural Invariants:
1. Persistence != Diagnostic Reasoning: Storing or retrieving data does not perform inference.
2. Persistence != Workflow Execution: Loading a workflow never triggers autonomous ECU dispatch.
3. Persistence != Knowledge Learning: Saving sessions never silently mutates global knowledge bases.
4. Persistence != Security Authorization: J-3 is storage, not J-5 access control.
5. Historical Data != Current Truth: Historical cases and old DTCs are context, never active truth.
6. Raw vs Derived Data Separation: Raw ECU byte payloads are bit-for-bit preserved, never overwritten.
7. Provenance & Lineage: Audit trails, timestamps, and causal references survive serialization.
8. Safe Deserialization: Strict schema validation; zero arbitrary code execution or pickle use.
9. Versioned & Migratable: Every record has schema_version; unknown future versions fail closed.
10. Atomic & Crash-Safe: Relational transactions ensure no partial or corrupted session writes.
"""

from __future__ import annotations

import abc
import collections
import contextlib
import copy
import dataclasses
from dataclasses import dataclass, field
import hashlib
import json
import logging
import os
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union

# J-2 Platform Abstraction Integration
from platform_abstraction import PlatformManager

# G, H, I Domain Imports (Safely imported for type annotations and mappers)
from extended_did import VehicleContext
from advanced_fault_analysis import DTCRecord, FaultEvidence, FaultHypothesis
from vehicle_diagnostic_graph import DiagnosticGraph, GraphNode, GraphEdge, GraphNodeType, GraphEdgeType
from diagnostic_workflow_engine import DiagnosticWorkflow, WorkflowState, WorkflowStage
from historical_case_analysis import HistoricalDiagnosticCase
from advanced_reasoning_layer import DiagnosticReasoningSession

logger = logging.getLogger("seyyanen.persistence")

CURRENT_SCHEMA_VERSION = 1


# =====================================================================
# 1. STRUCTURED PERSISTENCE ERROR MODEL
# =====================================================================

class PersistenceError(Exception):
    """
    Base exception for all persistence and storage operations.
    Preserves invariant: is_persistence_error=True and is_communication_failure=False.
    Persistence failures are infrastructure errors, NEVER vehicle ECU defects.
    """
    def __init__(self, message: str, collection: Optional[str] = None, record_id: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.collection = collection
        self.record_id = record_id
        self.is_persistence_error = True
        self.is_communication_failure = False
        self.timestamp = time.time()

    def __str__(self) -> str:
        ctx = ""
        if self.collection:
            ctx += f" [{self.collection}"
            if self.record_id:
                ctx += f":{self.record_id}"
            ctx += "]"
        return f"[{self.__class__.__name__}]{ctx} {self.message}"


class RecordNotFoundError(PersistenceError):
    """Requested record ID does not exist in storage."""
    pass


class UnsupportedSchemaVersionError(PersistenceError):
    """Record schema version is newer than current application support (fail closed)."""
    pass


class CorruptedPersistenceDataError(PersistenceError):
    """Serialized data failed integrity checks, validation, or JSON decoding."""
    pass


class StorageBackendError(PersistenceError):
    """Low-level database connection, I/O, disk full, or lock failure."""
    pass


class DuplicateRecordError(PersistenceError):
    """Attempted to insert an existing primary key when overwrite is disabled."""
    pass


class UnsafeDeserializationError(PersistenceError):
    """Payload contains disallowed types, unexpected structures, or malicious attributes."""
    pass


# =====================================================================
# 2. CANONICAL PERSISTENCE MODELS
# =====================================================================

@dataclass
class DiagnosticSessionRecord:
    """
    Canonical persisted session record preserving full identity,
    vehicle/ECU context, acquisition summaries, DTCs, findings,
    hypotheses, test results, technician notes, and verification outcomes.
    """
    session_id: str
    vehicle_context: Dict[str, Any]
    ecu_contexts: Dict[str, Any] = field(default_factory=dict)
    adapter_info: Dict[str, Any] = field(default_factory=dict)
    start_timestamp: float = field(default_factory=time.time)
    end_timestamp: Optional[float] = None
    session_state: str = "ACTIVE"
    dtc_records: List[Dict[str, Any]] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    hypotheses: List[Dict[str, Any]] = field(default_factory=list)
    selected_tests: List[Dict[str, Any]] = field(default_factory=list)
    executed_tests: List[Dict[str, Any]] = field(default_factory=list)
    technician_observations: List[Dict[str, Any]] = field(default_factory=list)
    repair_verifications: List[Dict[str, Any]] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)
    application_session_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: int = CURRENT_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "application_session_id": self.application_session_id,
            "user_id": self.user_id,
            "vehicle_context": copy.deepcopy(self.vehicle_context),
            "ecu_contexts": copy.deepcopy(self.ecu_contexts),
            "adapter_info": copy.deepcopy(self.adapter_info),
            "start_timestamp": round(self.start_timestamp, 3),
            "end_timestamp": round(self.end_timestamp, 3) if self.end_timestamp else None,
            "session_state": self.session_state,
            "dtc_records": copy.deepcopy(self.dtc_records),
            "findings": copy.deepcopy(self.findings),
            "hypotheses": copy.deepcopy(self.hypotheses),
            "selected_tests": copy.deepcopy(self.selected_tests),
            "executed_tests": copy.deepcopy(self.executed_tests),
            "technician_observations": copy.deepcopy(self.technician_observations),
            "repair_verifications": copy.deepcopy(self.repair_verifications),
            "provenance": copy.deepcopy(self.provenance),
            "metadata": copy.deepcopy(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagnosticSessionRecord":
        sid = data.get("session_id")
        if not sid:
            raise CorruptedPersistenceDataError("Missing required field 'session_id' in session record.")
        return cls(
            session_id=str(sid),
            application_session_id=data.get("application_session_id"),
            user_id=data.get("user_id"),
            vehicle_context=dict(data.get("vehicle_context", {})),
            ecu_contexts=dict(data.get("ecu_contexts", {})),
            adapter_info=dict(data.get("adapter_info", {})),
            start_timestamp=float(data.get("start_timestamp", time.time())),
            end_timestamp=float(data["end_timestamp"]) if data.get("end_timestamp") is not None else None,
            session_state=str(data.get("session_state", "ACTIVE")),
            dtc_records=list(data.get("dtc_records", [])),
            findings=list(data.get("findings", [])),
            hypotheses=list(data.get("hypotheses", [])),
            selected_tests=list(data.get("selected_tests", [])),
            executed_tests=list(data.get("executed_tests", [])),
            technician_observations=list(data.get("technician_observations", [])),
            repair_verifications=list(data.get("repair_verifications", [])),
            provenance=dict(data.get("provenance", {})),
            metadata=dict(data.get("metadata", {})),
            schema_version=int(data.get("schema_version", CURRENT_SCHEMA_VERSION)),
        )


@dataclass
class RawAcquisitionRecord:
    """
    Preserves exact bit-for-bit raw ECU communication bytes
    with precise timestamps, source ECU, and session lineage.
    """
    acquisition_id: str
    session_id: str
    source_ecu: str
    command_or_pid: str
    timestamp: float
    raw_payload: bytes
    payload_length: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: int = CURRENT_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "acquisition_id": self.acquisition_id,
            "session_id": self.session_id,
            "source_ecu": self.source_ecu,
            "command_or_pid": self.command_or_pid,
            "timestamp": round(self.timestamp, 3),
            "payload_length": self.payload_length,
            "metadata": copy.deepcopy(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], raw_payload: bytes) -> "RawAcquisitionRecord":
        return cls(
            acquisition_id=str(data["acquisition_id"]),
            session_id=str(data["session_id"]),
            source_ecu=str(data.get("source_ecu", "ECM")),
            command_or_pid=str(data.get("command_or_pid", "")),
            timestamp=float(data.get("timestamp", time.time())),
            raw_payload=raw_payload,
            payload_length=int(data.get("payload_length", len(raw_payload))),
            metadata=dict(data.get("metadata", {})),
            schema_version=int(data.get("schema_version", CURRENT_SCHEMA_VERSION)),
        )


# =====================================================================
# 3. SCHEMA MIGRATION REGISTRY
# =====================================================================

class SchemaMigrationRegistry:
    """
    Controlled, deterministic forward schema evolution.
    Guarantees that older schema versions migrate safely to the current
    version without data loss or silent misinterpretation.
    """
    _migrations: Dict[Tuple[str, int, int], Callable[[Dict[str, Any]], Dict[str, Any]]] = {}

    @classmethod
    def register_migration(
        cls,
        collection: str,
        from_ver: int,
        to_ver: int,
        handler: Callable[[Dict[str, Any]], Dict[str, Any]]
    ) -> None:
        cls._migrations[(collection, from_ver, to_ver)] = handler

    @classmethod
    def migrate(cls, collection: str, data: Dict[str, Any]) -> Dict[str, Any]:
        version = data.get("schema_version", 1)
        if version > CURRENT_SCHEMA_VERSION:
            raise UnsupportedSchemaVersionError(
                f"Record schema version {version} exceeds maximum supported version {CURRENT_SCHEMA_VERSION}.",
                collection=collection,
                record_id=data.get("session_id") or data.get("workflow_id") or data.get("case_id")
            )

        current_data = copy.deepcopy(data)
        curr_ver = version
        while curr_ver < CURRENT_SCHEMA_VERSION:
            next_ver = curr_ver + 1
            key = (collection, curr_ver, next_ver)
            if key in cls._migrations:
                current_data = cls._migrations[key](current_data)
                curr_ver = next_ver
                current_data["schema_version"] = curr_ver
            else:
                # Default safe forward compatibility bump if no structural transform required
                curr_ver = next_ver
                current_data["schema_version"] = curr_ver

        return current_data


# =====================================================================
# 4. CANONICAL PERSISTENCE BACKEND INTERFACE
# =====================================================================

class IPersistenceBackend(abc.ABC):
    """
    Abstract storage contract decoupling diagnostic intelligence
    from concrete databases, filesystems, or storage engines.
    """
    @abc.abstractmethod
    def initialize(self) -> None:
        """Sets up database tables, schemas, and indices."""
        pass

    @abc.abstractmethod
    def close(self) -> None:
        """Closes all storage handles cleanly."""
        pass

    @abc.abstractmethod
    def save_record(
        self,
        collection: str,
        record_id: str,
        data: Dict[str, Any],
        raw_payload: Optional[bytes] = None,
        vehicle_id: Optional[str] = None,
        ecu_id: Optional[str] = None,
    ) -> bool:
        """Saves or updates a structured record atomically."""
        pass

    @abc.abstractmethod
    def get_record(self, collection: str, record_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a structured record by collection and ID."""
        pass

    @abc.abstractmethod
    def get_raw_payload(self, collection: str, record_id: str) -> Optional[bytes]:
        """Retrieves raw byte payload associated with a record."""
        pass

    @abc.abstractmethod
    def delete_record(self, collection: str, record_id: str) -> bool:
        """Deletes a record explicitly by ID."""
        pass

    @abc.abstractmethod
    def list_records(
        self,
        collection: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Queries structured records with indexed bounding."""
        pass

    @abc.abstractmethod
    def count_records(self, collection: str, filters: Optional[Dict[str, Any]] = None) -> int:
        """Returns count of matching records in collection."""
        pass

    @abc.abstractmethod
    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        """Context manager providing atomic multi-record transactions."""
        pass


# =====================================================================
# 5. SQLITE PERSISTENCE BACKEND (PRODUCTION EMBEDDED ENGINE)
# =====================================================================

class SQLitePersistenceBackend(IPersistenceBackend):
    """
    Production-grade embedded relational persistence backend using sqlite3.
    Provides ACID transaction guarantees, indexed queries, and binary blob storage.
    """
    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        if db_path is None:
            # Integrate with J-2 PlatformManager standard paths
            app_dir = PlatformManager.get_app_data_path()
            app_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = app_dir / "seyyanen_diagnostics.db"
        elif str(db_path) == ":memory:":
            self.db_path = Path(":memory:")
        else:
            self.db_path = Path(db_path)
            if self.db_path.parent and not self.db_path.parent.exists():
                self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._in_transaction = False

    def initialize(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            try:
                db_str = str(self.db_path) if str(self.db_path) != ":memory:" else ":memory:"
                self._conn = sqlite3.connect(db_str, check_same_thread=False)
                self._conn.row_factory = sqlite3.Row
                # Enable WAL mode for safe concurrent reads if on physical disk
                if db_str != ":memory:":
                    self._conn.execute("PRAGMA journal_mode = WAL;")
                self._conn.execute("PRAGMA foreign_keys = ON;")

                self._create_tables()
            except Exception as e:
                raise StorageBackendError(f"Failed to initialize SQLite storage at '{self.db_path}': {e}") from e

    def _create_tables(self) -> None:
        assert self._conn is not None
        with self._conn:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS records (
                    collection TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    vehicle_id TEXT,
                    ecu_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    data_json TEXT NOT NULL,
                    raw_blob BLOB,
                    PRIMARY KEY (collection, record_id)
                );
            """)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_records_col_veh ON records(collection, vehicle_id);")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_records_col_ecu ON records(collection, ecu_id);")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_records_col_created ON records(collection, created_at);")

    def close(self) -> None:
        with self._lock:
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def __del__(self) -> None:
        self.close()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            self.initialize()
            assert self._conn is not None
            if self._in_transaction:
                yield
                return

            self._in_transaction = True
            try:
                self._conn.execute("BEGIN IMMEDIATE;")
                yield
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
            finally:
                self._in_transaction = False

    def save_record(
        self,
        collection: str,
        record_id: str,
        data: Dict[str, Any],
        raw_payload: Optional[bytes] = None,
        vehicle_id: Optional[str] = None,
        ecu_id: Optional[str] = None,
    ) -> bool:
        if not collection or not record_id:
            raise PersistenceError("collection and record_id are required non-empty strings.")

        with self._lock:
            self.initialize()
            assert self._conn is not None
            now = time.time()
            schema_ver = int(data.get("schema_version", CURRENT_SCHEMA_VERSION))

            # Extract vehicle_id from data if not explicitly provided
            if not vehicle_id:
                if isinstance(data.get("vehicle_context"), dict):
                    vehicle_id = data["vehicle_context"].get("vin") or data["vehicle_context"].get("vehicle_id")
                elif "vehicle_id" in data:
                    vehicle_id = data["vehicle_id"]

            try:
                data_str = json.dumps(data, ensure_ascii=False)
            except Exception as e:
                raise CorruptedPersistenceDataError(f"Failed to serialize record data to JSON: {e}", collection, record_id) from e

            try:
                query = """
                    INSERT INTO records (collection, record_id, schema_version, vehicle_id, ecu_id, created_at, updated_at, data_json, raw_blob)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(collection, record_id) DO UPDATE SET
                        schema_version = excluded.schema_version,
                        vehicle_id = COALESCE(excluded.vehicle_id, records.vehicle_id),
                        ecu_id = COALESCE(excluded.ecu_id, records.ecu_id),
                        updated_at = excluded.updated_at,
                        data_json = excluded.data_json,
                        raw_blob = COALESCE(excluded.raw_blob, records.raw_blob);
                """
                if self._in_transaction:
                    self._conn.execute(query, (collection, record_id, schema_ver, vehicle_id, ecu_id, now, now, data_str, raw_payload))
                else:
                    with self._conn:
                        self._conn.execute(query, (collection, record_id, schema_ver, vehicle_id, ecu_id, now, now, data_str, raw_payload))
                return True
            except Exception as e:
                raise StorageBackendError(f"Database write failed for [{collection}:{record_id}]: {e}", collection, record_id) from e

    def get_record(self, collection: str, record_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self.initialize()
            assert self._conn is not None
            try:
                cur = self._conn.execute(
                    "SELECT data_json, schema_version FROM records WHERE collection = ? AND record_id = ?;",
                    (collection, record_id)
                )
                row = cur.fetchone()
                if not row:
                    return None

                data = json.loads(row["data_json"])
                # Apply schema migration pipeline if necessary
                return SchemaMigrationRegistry.migrate(collection, data)
            except UnsupportedSchemaVersionError:
                raise
            except json.JSONDecodeError as e:
                raise CorruptedPersistenceDataError(f"Malformed JSON in stored record: {e}", collection, record_id) from e
            except Exception as e:
                raise StorageBackendError(f"Failed to read record [{collection}:{record_id}]: {e}", collection, record_id) from e

    def get_raw_payload(self, collection: str, record_id: str) -> Optional[bytes]:
        with self._lock:
            self.initialize()
            assert self._conn is not None
            cur = self._conn.execute(
                "SELECT raw_blob FROM records WHERE collection = ? AND record_id = ?;",
                (collection, record_id)
            )
            row = cur.fetchone()
            if not row:
                return None
            return row["raw_blob"]

    def delete_record(self, collection: str, record_id: str) -> bool:
        with self._lock:
            self.initialize()
            assert self._conn is not None
            try:
                if self._in_transaction:
                    cur = self._conn.execute(
                        "DELETE FROM records WHERE collection = ? AND record_id = ?;",
                        (collection, record_id)
                    )
                else:
                    with self._conn:
                        cur = self._conn.execute(
                            "DELETE FROM records WHERE collection = ? AND record_id = ?;",
                            (collection, record_id)
                        )
                return cur.rowcount > 0
            except Exception as e:
                raise StorageBackendError(f"Failed to delete record [{collection}:{record_id}]: {e}", collection, record_id) from e

    def list_records(
        self,
        collection: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        with self._lock:
            self.initialize()
            assert self._conn is not None
            query_parts = ["SELECT data_json, schema_version FROM records WHERE collection = ?"]
            params: List[Any] = [collection]

            if filters:
                if "vehicle_id" in filters and filters["vehicle_id"]:
                    query_parts.append("AND vehicle_id = ?")
                    params.append(filters["vehicle_id"])
                if "ecu_id" in filters and filters["ecu_id"]:
                    query_parts.append("AND ecu_id = ?")
                    params.append(filters["ecu_id"])
                if "since_timestamp" in filters and filters["since_timestamp"]:
                    query_parts.append("AND created_at >= ?")
                    params.append(float(filters["since_timestamp"]))

            query_parts.append("ORDER BY created_at DESC LIMIT ? OFFSET ?;")
            params.extend([int(limit), int(offset)])

            try:
                cur = self._conn.execute(" ".join(query_parts), params)
                results: List[Dict[str, Any]] = []
                for row in cur.fetchall():
                    data = json.loads(row["data_json"])
                    results.append(SchemaMigrationRegistry.migrate(collection, data))
                return results
            except Exception as e:
                raise StorageBackendError(f"Query failed on collection '{collection}': {e}", collection) from e

    def count_records(self, collection: str, filters: Optional[Dict[str, Any]] = None) -> int:
        with self._lock:
            self.initialize()
            assert self._conn is not None
            query_parts = ["SELECT COUNT(*) as cnt FROM records WHERE collection = ?"]
            params: List[Any] = [collection]

            if filters:
                if "vehicle_id" in filters and filters["vehicle_id"]:
                    query_parts.append("AND vehicle_id = ?")
                    params.append(filters["vehicle_id"])
                if "ecu_id" in filters and filters["ecu_id"]:
                    query_parts.append("AND ecu_id = ?")
                    params.append(filters["ecu_id"])

            cur = self._conn.execute(" ".join(query_parts), params)
            row = cur.fetchone()
            return int(row["cnt"]) if row else 0


# =====================================================================
# 6. IN-MEMORY PERSISTENCE BACKEND (TEST & EPHEMERAL DOUBLE)
# =====================================================================

class InMemoryPersistenceBackend(IPersistenceBackend):
    """
    Deterministic, fast In-Memory storage backend.
    Enables unit testing and isolated evaluation without disk side-effects.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._store: Dict[str, Dict[str, Dict[str, Any]]] = collections.defaultdict(dict)
        self._raw_store: Dict[str, Dict[str, bytes]] = collections.defaultdict(dict)
        self._snapshot: Optional[Dict[str, Any]] = None
        self._in_transaction = False

    def initialize(self) -> None:
        pass

    def close(self) -> None:
        with self._lock:
            self._store.clear()
            self._raw_store.clear()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            if self._in_transaction:
                yield
                return

            self._in_transaction = True
            # Deep snapshot for transactional rollback simulation
            old_store = copy.deepcopy(self._store)
            old_raw = copy.deepcopy(self._raw_store)
            try:
                yield
            except BaseException:
                self._store = old_store
                self._raw_store = old_raw
                raise
            finally:
                self._in_transaction = False

    def save_record(
        self,
        collection: str,
        record_id: str,
        data: Dict[str, Any],
        raw_payload: Optional[bytes] = None,
        vehicle_id: Optional[str] = None,
        ecu_id: Optional[str] = None,
    ) -> bool:
        if not collection or not record_id:
            raise PersistenceError("collection and record_id are required non-empty strings.")

        with self._lock:
            # Simulate strict serialization check
            try:
                _ = json.dumps(data)
            except Exception as e:
                raise CorruptedPersistenceDataError(f"Data not serializable: {e}", collection, record_id) from e

            # Extract vehicle_id from data if not explicitly provided
            veh = vehicle_id
            if not veh:
                if isinstance(data.get("vehicle_context"), dict):
                    veh = data["vehicle_context"].get("vin") or data["vehicle_context"].get("vehicle_id")
                elif "vehicle_id" in data:
                    veh = data["vehicle_id"]

            record_entry = {
                "collection": collection,
                "record_id": record_id,
                "data": copy.deepcopy(data),
                "vehicle_id": veh,
                "ecu_id": ecu_id,
                "created_at": time.time(),
            }
            self._store[collection][record_id] = record_entry
            if raw_payload is not None:
                self._raw_store[collection][record_id] = bytes(raw_payload)
            return True

    def get_record(self, collection: str, record_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            entry = self._store.get(collection, {}).get(record_id)
            if not entry:
                return None
            data = copy.deepcopy(entry["data"])
            return SchemaMigrationRegistry.migrate(collection, data)

    def get_raw_payload(self, collection: str, record_id: str) -> Optional[bytes]:
        with self._lock:
            return self._raw_store.get(collection, {}).get(record_id)

    def delete_record(self, collection: str, record_id: str) -> bool:
        with self._lock:
            if collection in self._store and record_id in self._store[collection]:
                del self._store[collection][record_id]
                if collection in self._raw_store and record_id in self._raw_store[collection]:
                    del self._raw_store[collection][record_id]
                return True
            return False

    def list_records(
        self,
        collection: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        with self._lock:
            entries = list(self._store.get(collection, {}).values())
            if filters:
                if "vehicle_id" in filters and filters["vehicle_id"]:
                    entries = [e for e in entries if e.get("vehicle_id") == filters["vehicle_id"]]
                if "ecu_id" in filters and filters["ecu_id"]:
                    entries = [e for e in entries if e.get("ecu_id") == filters["ecu_id"]]
                if "since_timestamp" in filters and filters["since_timestamp"]:
                    entries = [e for e in entries if e.get("created_at", 0) >= float(filters["since_timestamp"])]

            entries.sort(key=lambda x: x.get("created_at", 0), reverse=True)
            paginated = entries[offset: offset + limit]
            return [SchemaMigrationRegistry.migrate(collection, copy.deepcopy(e["data"])) for e in paginated]

    def count_records(self, collection: str, filters: Optional[Dict[str, Any]] = None) -> int:
        return len(self.list_records(collection, filters=filters, limit=100000))


# =====================================================================
# 7. UNIFIED DIAGNOSTIC REPOSITORY (CANONICAL PERSISTENCE FACADE)
# =====================================================================

class DiagnosticRepository:
    """
    Primary Domain Repository Facade for Seyyanen Data Persistence.
    Provides type-safe, validated storage operations for Sessions,
    Workflows, Historical Cases, Reasoning Sessions, and Diagnostic Graphs.
    """
    COLLECTION_SESSIONS = "diagnostic_sessions"
    COLLECTION_WORKFLOWS = "diagnostic_workflows"
    COLLECTION_HISTORICAL_CASES = "historical_cases"
    COLLECTION_REASONING_SESSIONS = "reasoning_sessions"
    COLLECTION_GRAPHS = "diagnostic_graphs"
    COLLECTION_RAW_ACQUISITIONS = "raw_acquisitions"
    COLLECTION_USERS = "application_users"
    COLLECTION_APPLICATION_SESSIONS = "application_sessions"
    COLLECTION_SESSION_AUDIT_EVENTS = "session_audit_events"
    COLLECTION_SECURITY_AUDIT_EVENTS = "security_audit_events"

    def __init__(self, backend: Optional[IPersistenceBackend] = None):
        self._backend = backend or SQLitePersistenceBackend()
        self._backend.initialize()

    @property
    def backend(self) -> IPersistenceBackend:
        return self._backend

    def close(self) -> None:
        self._backend.close()

    def count_records(self, collection: str, filters: Optional[Dict[str, Any]] = None) -> int:
        """Returns the number of records matching the filters in the given collection."""
        return self._backend.count_records(collection, filters=filters)

    # -----------------------------------------------------------------
    # A. Diagnostic Session Persistence
    # -----------------------------------------------------------------

    def save_session(self, session: DiagnosticSessionRecord) -> str:
        """Saves a structured diagnostic session record."""
        if not session.session_id:
            raise PersistenceError("Session must have a valid session_id.")

        veh_id = session.vehicle_context.get("vin") or session.vehicle_context.get("vehicle_id")
        self._backend.save_record(
            collection=self.COLLECTION_SESSIONS,
            record_id=session.session_id,
            data=session.to_dict(),
            vehicle_id=veh_id,
        )
        return session.session_id

    def get_session(self, session_id: str) -> Optional[DiagnosticSessionRecord]:
        """Retrieves and deserializes a diagnostic session."""
        data = self._backend.get_record(self.COLLECTION_SESSIONS, session_id)
        if not data:
            return None
        return DiagnosticSessionRecord.from_dict(data)

    def list_sessions(
        self,
        vehicle_id: Optional[str] = None,
        ecu_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[DiagnosticSessionRecord]:
        """Queries diagnostic sessions with optional vehicle/ECU filters."""
        filters: Dict[str, Any] = {}
        if vehicle_id:
            filters["vehicle_id"] = vehicle_id
        if ecu_id:
            filters["ecu_id"] = ecu_id

        raw_list = self._backend.list_records(
            self.COLLECTION_SESSIONS,
            filters=filters,
            limit=limit,
            offset=offset,
        )
        return [DiagnosticSessionRecord.from_dict(d) for d in raw_list]

    # -----------------------------------------------------------------
    # B. Diagnostic Workflow Persistence (Phase H-5)
    # -----------------------------------------------------------------

    def save_workflow(self, workflow: DiagnosticWorkflow) -> str:
        """
        Persists a DiagnosticWorkflow state without executing any commands.
        Preserves H-5 state, stages, sequences, decisions, and technician gates.
        """
        if not workflow.workflow_id:
            raise PersistenceError("Workflow must have a valid workflow_id.")

        data = workflow.to_dict()
        data["schema_version"] = CURRENT_SCHEMA_VERSION
        self._backend.save_record(
            collection=self.COLLECTION_WORKFLOWS,
            record_id=workflow.workflow_id,
            data=data,
            vehicle_id=workflow.vehicle_id,
        )
        return workflow.workflow_id

    def get_workflow(self, workflow_id: str) -> Optional[DiagnosticWorkflow]:
        """Loads and safely reconstructs a DiagnosticWorkflow."""
        data = self._backend.get_record(self.COLLECTION_WORKFLOWS, workflow_id)
        if not data:
            return None
        return DiagnosticWorkflow.from_dict(data)

    # -----------------------------------------------------------------
    # C. Historical Case Persistence (Phase I-4)
    # -----------------------------------------------------------------

    def save_historical_case(self, case: HistoricalDiagnosticCase) -> str:
        """
        Persists an empirical historical diagnostic case.
        Preserves the invariant: HISTORICAL DATA IS EVIDENCE, NOT PROOF.
        """
        if not case.case_id:
            raise PersistenceError("Historical case must have a valid case_id.")

        data = case.to_dict()
        data["schema_version"] = CURRENT_SCHEMA_VERSION
        veh_id = getattr(case.vehicle_context, "vin", None) or getattr(case.vehicle_context, "vehicle_id", None)
        self._backend.save_record(
            collection=self.COLLECTION_HISTORICAL_CASES,
            record_id=case.case_id,
            data=data,
            vehicle_id=veh_id,
        )
        return case.case_id

    def get_historical_case(self, case_id: str) -> Optional[HistoricalDiagnosticCase]:
        """Loads and safely reconstructs a HistoricalDiagnosticCase."""
        data = self._backend.get_record(self.COLLECTION_HISTORICAL_CASES, case_id)
        if not data:
            return None
        return HistoricalDiagnosticCase.from_dict(data)

    def list_historical_cases(
        self,
        vehicle_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[HistoricalDiagnosticCase]:
        """Queries historical diagnostic cases."""
        filters = {"vehicle_id": vehicle_id} if vehicle_id else None
        raw_list = self._backend.list_records(
            self.COLLECTION_HISTORICAL_CASES,
            filters=filters,
            limit=limit,
            offset=offset,
        )
        return [HistoricalDiagnosticCase.from_dict(d) for d in raw_list]

    # -----------------------------------------------------------------
    # D. Diagnostic Reasoning Session Persistence (Phase I-5)
    # -----------------------------------------------------------------

    def save_reasoning_session(self, session: DiagnosticReasoningSession) -> str:
        """
        Persists an evaluated DiagnosticReasoningSession.
        Preserves candidates, scores, contradictions, uncertainty, and traces.
        """
        if not session.reasoning_id:
            raise PersistenceError("Reasoning session must have a valid reasoning_id.")

        data = session.to_dict()
        data["schema_version"] = CURRENT_SCHEMA_VERSION
        veh_id = getattr(session.vehicle_context, "vin", None)
        self._backend.save_record(
            collection=self.COLLECTION_REASONING_SESSIONS,
            record_id=session.reasoning_id,
            data=data,
            vehicle_id=veh_id,
        )
        return session.reasoning_id

    def get_reasoning_session(self, reasoning_id: str) -> Optional[DiagnosticReasoningSession]:
        """Loads and safely reconstructs a DiagnosticReasoningSession."""
        data = self._backend.get_record(self.COLLECTION_REASONING_SESSIONS, reasoning_id)
        if not data:
            return None
        return DiagnosticReasoningSession.from_dict(data)

    # -----------------------------------------------------------------
    # E. Vehicle Diagnostic Graph Persistence (Phase G-5)
    # -----------------------------------------------------------------

    def save_diagnostic_graph(self, graph: DiagnosticGraph, session_id: Optional[str] = None) -> str:
        """
        Persists a G-5 vehicle diagnostic evidence graph.
        Preserves node and edge semantics, confidence, and provenance.
        Invariant: RELATIONSHIP != CAUSALITY is strictly preserved.
        """
        graph_id = graph.vehicle_id or f"graph:{uuid.uuid4().hex[:8]}"
        all_edges = list(graph._edges_by_id.values())

        graph_dict = {
            "graph_id": graph_id,
            "vehicle_id": graph.vehicle_id,
            "metadata": copy.deepcopy(graph.metadata),
            "session_ids": list(graph.session_ids),
            "nodes": [n.to_dict() for n in graph.nodes.values()],
            "edges": [e.to_dict() for e in all_edges],
            "schema_version": CURRENT_SCHEMA_VERSION,
        }
        if session_id:
            graph_dict["session_ids"].append(session_id)

        self._backend.save_record(
            collection=self.COLLECTION_GRAPHS,
            record_id=graph_id,
            data=graph_dict,
            vehicle_id=graph.vehicle_id,
        )
        return graph_id

    def get_diagnostic_graph(self, vehicle_id_or_graph_id: str) -> Optional[DiagnosticGraph]:
        """Loads and reconstructs a DiagnosticGraph."""
        data = self._backend.get_record(self.COLLECTION_GRAPHS, vehicle_id_or_graph_id)
        if not data:
            # Try finding by vehicle_id filter if queried by vehicle
            matched = self._backend.list_records(
                self.COLLECTION_GRAPHS,
                filters={"vehicle_id": vehicle_id_or_graph_id},
                limit=1,
            )
            if not matched:
                return None
            data = matched[0]

        graph = DiagnosticGraph(vehicle_id=data.get("vehicle_id"), metadata=data.get("metadata", {}))
        for nd in data.get("nodes", []):
            graph.add_node(GraphNode.from_dict(nd))
        for ed in data.get("edges", []):
            graph.add_edge(GraphEdge.from_dict(ed))
        for sid in data.get("session_ids", []):
            graph.session_ids.add(sid)

        return graph

    # -----------------------------------------------------------------
    # F. Raw Acquisition Data Persistence
    # -----------------------------------------------------------------

    def save_raw_acquisition(
        self,
        session_id: str,
        source_ecu: str,
        command_or_pid: str,
        raw_payload: bytes,
        metadata: Optional[Dict[str, Any]] = None,
        acquisition_id: Optional[str] = None,
    ) -> str:
        """
        Stores an exact, unaltered raw binary acquisition payload.
        Preserves raw bytes bit-for-bit with timestamps and source context.
        """
        acq_id = acquisition_id or f"raw_{uuid.uuid4().hex[:12]}"
        record = RawAcquisitionRecord(
            acquisition_id=acq_id,
            session_id=session_id,
            source_ecu=source_ecu,
            command_or_pid=command_or_pid,
            timestamp=time.time(),
            raw_payload=raw_payload,
            payload_length=len(raw_payload),
            metadata=metadata or {},
        )
        self._backend.save_record(
            collection=self.COLLECTION_RAW_ACQUISITIONS,
            record_id=acq_id,
            data=record.to_dict(),
            raw_payload=raw_payload,
            ecu_id=source_ecu,
        )
        return acq_id

    def get_raw_acquisition(self, acquisition_id: str) -> Optional[Tuple[bytes, Dict[str, Any]]]:
        """Retrieves raw byte payload and associated metadata."""
        data = self._backend.get_record(self.COLLECTION_RAW_ACQUISITIONS, acquisition_id)
        if not data:
            return None
        payload = self._backend.get_raw_payload(self.COLLECTION_RAW_ACQUISITIONS, acquisition_id)
        return (payload or b"", data)

    # -----------------------------------------------------------------
    # G. Technician Observation & Repair Verification Helpers
    # -----------------------------------------------------------------

    def record_technician_observation(self, session_id: str, observation: Dict[str, Any]) -> bool:
        """Appends a technician observation to an existing session atomically."""
        with self._backend.transaction():
            session = self.get_session(session_id)
            if not session:
                raise RecordNotFoundError(f"Cannot record observation: session '{session_id}' not found.", self.COLLECTION_SESSIONS, session_id)
            obs_entry = copy.deepcopy(observation)
            obs_entry["recorded_at"] = time.time()
            session.technician_observations.append(obs_entry)
            self.save_session(session)
            return True

    def record_repair_verification(self, session_id: str, verification: Dict[str, Any]) -> bool:
        """Appends a repair verification record to an existing session atomically."""
        with self._backend.transaction():
            session = self.get_session(session_id)
            if not session:
                raise RecordNotFoundError(f"Cannot record repair verification: session '{session_id}' not found.", self.COLLECTION_SESSIONS, session_id)
            ver_entry = copy.deepcopy(verification)
            ver_entry["recorded_at"] = time.time()
            session.repair_verifications.append(ver_entry)
            self.save_session(session)
            return True

    # -----------------------------------------------------------------
    # H. Application User Persistence (Phase J-4)
    # -----------------------------------------------------------------

    def save_user(self, user: Any) -> str:
        """Persists an ApplicationUser record."""
        data = user.to_dict() if hasattr(user, "to_dict") else dict(user)
        uid = str(data.get("user_id", "")).strip()
        if not uid:
            raise PersistenceError("ApplicationUser must have a non-empty user_id.")
        self._backend.save_record(
            collection=self.COLLECTION_USERS,
            record_id=uid,
            data=data,
        )
        return uid

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves an ApplicationUser record by ID."""
        return self._backend.get_record(self.COLLECTION_USERS, user_id)

    def list_users(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Lists ApplicationUser records with optional status filter."""
        records = self._backend.list_records(self.COLLECTION_USERS, limit=1000, offset=0)
        if status:
            records = [r for r in records if r.get("status") == status]
        return records[offset:offset + limit]

    # -----------------------------------------------------------------
    # I. Application Session Persistence (Phase J-4)
    # -----------------------------------------------------------------

    def save_application_session(self, session: Any) -> str:
        """Persists an ApplicationSession record."""
        data = session.to_dict() if hasattr(session, "to_dict") else dict(session)
        sid = str(data.get("application_session_id", "")).strip()
        if not sid:
            raise PersistenceError("ApplicationSession must have a non-empty application_session_id.")
        self._backend.save_record(
            collection=self.COLLECTION_APPLICATION_SESSIONS,
            record_id=sid,
            data=data,
        )
        return sid

    def get_application_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves an ApplicationSession record by ID."""
        return self._backend.get_record(self.COLLECTION_APPLICATION_SESSIONS, session_id)

    def list_application_sessions(
        self,
        user_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Lists ApplicationSession records with optional user_id and state filter."""
        records = self._backend.list_records(self.COLLECTION_APPLICATION_SESSIONS, limit=1000, offset=0)
        if user_id:
            records = [r for r in records if r.get("user_id") == user_id]
        if state:
            records = [r for r in records if r.get("state") == state]
        return records[offset:offset + limit]

    # -----------------------------------------------------------------
    # J. Session Audit Event Persistence (Phase J-4)
    # -----------------------------------------------------------------

    def save_audit_event(self, event: Any) -> str:
        """Persists a SessionAuditEvent record."""
        data = event.to_dict() if hasattr(event, "to_dict") else dict(event)
        eid = str(data.get("event_id", "")).strip()
        if not eid:
            raise PersistenceError("SessionAuditEvent must have a non-empty event_id.")
        self._backend.save_record(
            collection=self.COLLECTION_SESSION_AUDIT_EVENTS,
            record_id=eid,
            data=data,
        )
        return eid

    def list_audit_events(
        self,
        application_session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Lists SessionAuditEvent records with optional filtering."""
        records = self._backend.list_records(self.COLLECTION_SESSION_AUDIT_EVENTS, limit=1000, offset=0)
        if application_session_id:
            records = [r for r in records if r.get("application_session_id") == application_session_id]
        if user_id:
            records = [r for r in records if r.get("user_id") == user_id]
        return records[offset:offset + limit]

    # -----------------------------------------------------------------
    # K. Security Audit Event Persistence (Phase J-5)
    # -----------------------------------------------------------------

    def save_security_audit_event(self, event: Any) -> str:
        """Persists a SecurityAuditEvent record."""
        data = event.to_dict() if hasattr(event, "to_dict") else dict(event)
        eid = str(data.get("event_id", "")).strip()
        if not eid:
            raise PersistenceError("SecurityAuditEvent must have a non-empty event_id.")
        self._backend.save_record(
            collection=self.COLLECTION_SECURITY_AUDIT_EVENTS,
            record_id=eid,
            data=data,
        )
        return eid

    def list_security_audit_events(
        self,
        principal_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Lists SecurityAuditEvent records with optional filtering."""
        records = self._backend.list_records(self.COLLECTION_SECURITY_AUDIT_EVENTS, limit=1000, offset=0)
        if principal_id:
            records = [r for r in records if r.get("principal_id") == principal_id]
        if event_type:
            records = [r for r in records if r.get("event_type") == event_type]
        return records[offset:offset + limit]


# =====================================================================
# 8. GLOBAL PERSISTENCE MANAGER FACADE
# =====================================================================

class PersistenceManager:
    """
    Singleton-style global management facade for Seyyanen persistence.
    Allows injecting custom repositories or backends (e.g. for testing).
    """
    _repository: Optional[DiagnosticRepository] = None
    _lock = threading.RLock()

    @classmethod
    def get_repository(cls) -> DiagnosticRepository:
        with cls._lock:
            if cls._repository is None:
                cls._repository = DiagnosticRepository()
            return cls._repository

    @classmethod
    def set_repository(cls, repository: DiagnosticRepository) -> None:
        """Injects a custom repository (e.g. In-Memory for testing)."""
        with cls._lock:
            if cls._repository and cls._repository != repository:
                cls._repository.close()
            cls._repository = repository

    @classmethod
    def reset_to_default_repository(cls) -> None:
        """Restores the standard SQLite platform repository."""
        with cls._lock:
            if cls._repository:
                cls._repository.close()
            cls._repository = DiagnosticRepository()

    @classmethod
    def create_in_memory_repository(cls) -> DiagnosticRepository:
        """Factory helper creating an isolated In-Memory repository."""
        backend = InMemoryPersistenceBackend()
        return DiagnosticRepository(backend=backend)
