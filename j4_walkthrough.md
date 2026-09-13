# Phase J-4: User / Session Management Walkthrough

## Executive Summary
Phase J-4 introduces a clean user identity and application-session management layer for the Seyyanen automotive diagnostic platform.

The architectural role of Phase J-4 is:
$$\text{Application User} \xrightarrow{} \text{Application Session} \xrightarrow{} \text{Diagnostic Session (J-3)} \xrightarrow{} \text{Diagnostic Workflow (H-5)} \xrightarrow{} \text{Vehicle / ECU Context (C}\rightarrow\text{I)}$$

Phase J-4 establishes a formal boundary ensuring that the human operator, the runtime process instance, vehicle diagnostic operations, workflow states, and vehicle/ECU instances are strictly separated and never conflated.

---

## 1. Conceptual Taxonomy & Architectural Separation

Prior to Phase J-4, session references were used ambiguously across the codebase (e.g. diagnostic workflow sessions vs serial connection sessions vs temporary log files).

Phase J-4 explicitly defines and isolates the following entities:

| Entity | Domain Meaning | Example Identifier / Type | Scope & Lifecycle |
| :--- | :--- | :--- | :--- |
| **Application User** | The human technician / operator using Seyyanen | `ApplicationUser` (`user_id="tech_01"`) | Long-lived identity; survives application restarts |
| **Application Session** | One runtime process instance of Seyyanen | `ApplicationSession` (`appsess_9a4f21...`) | Bounded to a single runtime lifecycle (start $\rightarrow$ close/interrupt) |
| **Diagnostic Session** | One vehicle diagnostic operation | `DiagnosticSessionRecord` (`diag_sess_...`) | Bounded to a diagnostic encounter on a specific vehicle |
| **Workflow Session** | H-5 diagnostic workflow state machine | `DiagnosticWorkflow` (`wf_...`) | Orchestrated test/reasoning state inside a diagnostic session |
| **Vehicle Instance** | Physical vehicle being diagnosed | `VehicleContext` (VIN: `WAUZZZ...`) | Physical asset; completely independent of technician or app session |
| **ECU Instance** | Physical electronic control module | `target_ecu` (`"ECM"`, `"TCM"`, `"BCM"`) | Physical component; communicates via hardware adapter |
| **Historical Case** | Persisted empirical past diagnostic case | `HistoricalDiagnosticCase` (`case_...`) | Contextual reference evidence from past repairs |

### Core Architectural Invariants
1. **User $\neq$ ApplicationSession**: An operator is a human entity; an application session is a single process execution.
2. **ApplicationSession $\neq$ DiagnosticSession**: A single application runtime session can diagnose multiple vehicles sequentially.
3. **DiagnosticSession $\neq$ WorkflowSession**: Diagnostic sessions store raw and derived findings; H-5 workflows orchestrate procedure steps.
4. **User Identity $\neq$ Vehicle Identity**: User identity must **NEVER** be used to infer vehicle identity, ECU identity, engine, DTC, or diagnosis.
5. **User Identity is NEVER Diagnostic Evidence**: The technician's identity does not prove vehicle defect.
6. **Technician Observation $\neq$ Machine Finding**: Human observations are attributed to the user and clearly demarcated from raw sensor telemetry.
7. **Interrupted $\neq$ Completed**: Sessions recovered after an abnormal exit or crash are explicitly marked `INTERRUPTED`, never fabricated as `CLOSED`.
8. **Recovery Never Communicates**: Session recovery never communicates with an ECU, never executes tests, and never dispatches actuator commands.
9. **J-4 is NOT J-5**: J-4 is an identity and session lifecycle layer. Authentication (passwords, tokens) and authorization (roles, permissions) strictly belong to Phase J-5.
10. **Storage Authority**: All user, session, and audit models persist through the canonical J-3 persistence interface (`DiagnosticRepository`).

---

## 2. Application User Model & Offline-First Design

### Minimal Structured User Model
The `ApplicationUser` model encapsulates minimal operator identity without bloated personal data:
```python
@dataclass
class ApplicationUser:
    user_id: str
    display_name: str
    status: UserStatus = UserStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1
```

### Local / Default User Support
Seyyanen is designed as an offline-first automotive diagnostic tool:
- A default local user (`local_technician`, `"Local Technician"`) is automatically initialized upon first launch.
- The platform functions immediately without requiring cloud accounts, network connectivity, or fake login dialogs.

### J-5 Security Boundary
The user model strictly omits:
- Passwords and credential hashes.
- Authentication tokens / API keys.
- Access-control lists, roles, and administrative permissions.
Phase J-5 will introduce cryptographic security and permission management on top of J-4's stable identities.

---

## 3. Application Session Model & Lifecycle State Machine

An `ApplicationSession` represents a single running instance of Seyyanen:
```python
@dataclass
class ApplicationSession:
    application_session_id: str
    user_id: str
    state: ApplicationSessionState = ApplicationSessionState.CREATED
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    last_activity_time: float = field(default_factory=time.time)
    platform_context: Dict[str, Any] = field(default_factory=dict)
    app_version: str = "1.0.0"
    diagnostic_session_ids: List[str] = field(default_factory=list)
    active_diagnostic_session_id: Optional[str] = None
    adapter_info: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1
```

### Deterministic Lifecycle Transitions
The session state machine enforces strictly deterministic transitions:
```
             +------------+
             |  CREATED   |
             +------------+
               /    |    \
              /     |     \
             v      v      v
        +--------+ +----+ +-------------+
        | ACTIVE | |FAIL| | INTERRUPTED |
        +--------+ +----+ +-------------+
         |  ^  \
         |  |   \
         v  |    v
       +-----+  +--------+
       |PAUSE|  | CLOSED | (Terminal)
       +-----+  +--------+
```
- Valid transitions:
  - `CREATED` $\rightarrow$ `{ACTIVE, FAILED, INTERRUPTED}`
  - `ACTIVE` $\rightarrow$ `{PAUSED, CLOSED, FAILED, INTERRUPTED}`
  - `PAUSED` $\rightarrow$ `{ACTIVE, CLOSED, FAILED, INTERRUPTED}`
  - `CLOSED`, `FAILED`, `INTERRUPTED` are terminal states.
- Any invalid state transition immediately raises `InvalidSessionStateTransitionError`.

---

## 4. Active Diagnostic Session Lock & User Switching

To prevent accidental ownership corruption or race conditions during live diagnostic tests:
- When a diagnostic session is actively running on a vehicle (`active_diagnostic_session_id` is set), attempting to switch the active user or close the application session is locked.
- By default, attempting to switch users or close the application session raises `ActiveDiagnosticSessionLockError`.
- If explicitly forced (`force=True`), the system detaches the active diagnostic session, logs an explicit audit event (`DIAGNOSTIC_SESSION_DETACHED`), and completes the transition.

---

## 5. Crash Handling & Interrupted Session Recovery

If the application process terminates abnormally (e.g. power loss, operating system termination, or crash):
- Persisted sessions from the previous process run will remain in `ACTIVE`, `CREATED`, or `PAUSED` in storage.
- On next startup, `UserSessionManager.recover_interrupted_sessions()` scans persisted storage and reconciles unclosed sessions:
  - Unclosed sessions are transitioned to `INTERRUPTED` with `end_time` set to reconciliation time.
  - A structured audit event (`APPLICATION_INTERRUPTED`) is recorded with recovery metadata.
  - **Critical Invariant**: Interrupted sessions are **NEVER** fabricated as `CLOSED`.
  - **Safety Invariant**: Recovery **NEVER** initiates ECU communication, sends adapter frames, or auto-resumes diagnostic actuators. Diagnostic operations must be re-initiated by human operator action.

---

## 6. Audit Event Model

User operations and session lifecycle events are preserved in a bounded audit trail via `SessionAuditEvent`:
- Event types:
  - `USER_CREATED`, `USER_SELECTED`, `USER_SWITCHED`
  - `APPLICATION_STARTED`, `APPLICATION_PAUSED`, `APPLICATION_RESUMED`, `APPLICATION_CLOSED`, `APPLICATION_INTERRUPTED`
  - `DIAGNOSTIC_SESSION_LINKED`, `DIAGNOSTIC_SESSION_DETACHED`, `DIAGNOSTIC_SESSION_CLOSED`
- Stored in canonical J-3 collection `session_audit_events`.

---

## 7. Technician Observation Attribution vs Machine Findings

Phase J-4 provides `attribute_technician_observation()` to ensure technician notes are properly recorded:
- Technician notes retain `user_id`, `display_name`, and `application_session_id`.
- The record explicitly marks `is_technician_observation = True` and `is_machine_finding = False`.
- Machine findings (DTCs, freeze frames, live sensor acquisition bytes) are never altered or rewritten as user opinions.

---

## 8. Cross-Layer Integration

### J-1 Hardware / Adapter Integration
`ApplicationSession` records adapter metadata (`adapter_info`: adapter model, port, baudrate, protocol) for provenance without coupling J-4 to serial ports or VCI hardware control.

### J-2 Platform Abstraction Integration
`ApplicationSession` records platform environment (`platform_context`: OS family, architecture, Python version, standard paths) via `PlatformManager.get_info()`.

### J-3 Persistence Integration
`DiagnosticRepository` was extended with canonical collections:
- `COLLECTION_USERS = "application_users"`
- `COLLECTION_APPLICATION_SESSIONS = "application_sessions"`
- `COLLECTION_SESSION_AUDIT_EVENTS = "session_audit_events"`
Backward compatibility is strictly maintained: existing diagnostic records deserialize seamlessly with `user_id=None` and `application_session_id=None`.

---

## 9. Verification & Test Matrix (`test_phase_j4.py`)

A comprehensive unit test suite was implemented in `test_phase_j4.py` covering sections A through Z:

| Section | Test Case Description | Result |
| :--- | :--- | :--- |
| **A** | User creation, validation, unique ID generation, duplicate rejection | **PASS** |
| **B** | User identity model minimalism, local default user availability, no J-5 auth data | **PASS** |
| **C** | Multiple user registration, listing, and filtering | **PASS** |
| **D** | Active user selection and error handling for missing/inactive users | **PASS** |
| **E** | User switching and active diagnostic session locking (`ActiveDiagnosticSessionLockError`) | **PASS** |
| **F** | Application session creation, platform context extraction, version tracking | **PASS** |
| **G** | Application session lifecycle (`CREATED` $\rightarrow$ `ACTIVE` $\rightarrow$ `PAUSED` $\rightarrow$ `ACTIVE` $\rightarrow$ `CLOSED`) | **PASS** |
| **H** | Rejection of illegal state transitions (terminal `CLOSED` cannot resume) | **PASS** |
| **I** | Stable and globally unique application session ID generation | **PASS** |
| **J** | Diagnostic session linking and strict non-conflation (`ApplicationSession` $\neq$ `DiagnosticSession`) | **PASS** |
| **K** | Diagnostic workflow linking via diagnostic session (`ApplicationSession` $\rightarrow$ `DiagSession` $\rightarrow$ `Workflow`) | **PASS** |
| **L** | User identity $\neq$ vehicle identity separation (no vehicle fields on user, user is not evidence) | **PASS** |
| **M** | Persistence round-trip through J-3 using both SQLite and In-Memory storage engines | **PASS** |
| **N** | JSON serialization and deserialization round-trip for all J-4 models | **PASS** |
| **O** | Schema versioning and fail-closed handling for unsupported future schema versions | **PASS** |
| **P** | Explicit `INTERRUPTED` state representation on abnormal process termination | **PASS** |
| **Q** | Post-crash reconciliation semantics and audit trail logging | **PASS** |
| **R** | Safety verification: zero ECU communication during restart or session recovery | **PASS** |
| **S** | Concurrent application session isolation across multiple platform instances | **PASS** |
| **T** | Technician observation attribution preserving user provenance and non-machine classification | **PASS** |
| **U** | Report session metadata generation including operator, platform, and session lineage | **PASS** |
| **V** | Structured audit event emission and filtering | **PASS** |
| **W** | Privacy verification: zero personal tracking, GPS, or contact telemetry | **PASS** |
| **X** | J-2 Multi-Platform integration across operating system environments | **PASS** |
| **Y** | J-1 Adapter identity integration without hardware leaking | **PASS** |
| **Z** | Cross-phase regression and verification of all architectural invariants | **PASS** |

---

## 10. Known Limitations & Transition to Phase J-5

1. **Authentication & Passwords (Reserved for J-5)**:
   - J-4 establishes user identity but does not enforce password protection, biometric auth, or cryptographic identity tokens.
   - Anyone can switch between configured local users in J-4. Role-based access control and credential verification belong to Phase J-5.
2. **Access Control & Safety Roles (Reserved for J-5)**:
   - J-4 does not restrict high-risk diagnostic services (such as ECU flashing or actuator actuation) by user role.
   - Phase J-5 will introduce permissions (e.g. `TechnicianRole.MASTER`, `TechnicianRole.APPRENTICE`) to gate dangerous diagnostic actions.
3. **Single Local Database**:
   - J-4 stores users and sessions in the local SQLite database. Cloud sync or enterprise user synchronization is deferred beyond Phase J.
