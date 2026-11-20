# Phase J-5: Security & Permissions Walkthrough

## Executive Summary
Phase J-5 establishes a defensive-by-default, explicit, and enforceable security and permissions architecture for the Seyyanen automotive diagnostic platform.

The architectural role of Phase J-5 is:
$$\text{User Request} \xrightarrow{} \text{J-5 Authorization Gate} \xrightarrow{} \text{Diagnostic Safety Gate (G-1 / J-1)} \xrightarrow{} \text{Workflow Constraints (H)} \xrightarrow{} \text{Adapter (J-1)} \xrightarrow{} \text{Physical Transport}$$

Phase J-5 provides strict authorization boundaries ensuring that:
1. Operations have explicit, granular permissions.
2. Users have explicit identities from J-4 and assigned diagnostic roles.
3. Dangerous diagnostic operations require both authorization and diagnostic safety approval.
4. Default-deny is strictly enforced.
5. AI reasoning and automated workflows cannot bypass authorization or execute privileged actions directly.
6. Authorization failures remain distinct from vehicle diagnostic faults.

---

## 1. Security Architecture & Invariants

| Invariant | Principle | Enforcement Mechanism |
| :--- | :--- | :--- |
| **Authentication $\neq$ Authorization** | Identity is owned by J-4; permissions are owned by J-5. | `Principal` binds J-4 `user_id` without duplicating user lifecycle. |
| **Authorization $\neq$ Diagnostic Safety** | User permission NEVER replaces or weakens diagnostic safety. | `SecurityManager.authorize_diagnostic_operation` double-gate. |
| **Double-Gate Requirement** | Privileged diagnostic operations require BOTH gates to pass. | Authorization PASS + `ServiceSafetyPolicy` PASS. |
| **Default Deny** | Unknown operations, permissions, or roles evaluate to DENY. | Strict whitelist lookup; unmapped operations reject with `UNKNOWN_OPERATION`. |
| **Resource Scoping & Isolation** | Authority for vehicle A does not permit actions on vehicle B. | `_validate_resource_scope` enforces vehicle VIN and target ECU matching. |
| **Session Binding & Invalidation** | Privileged grants are bound to the active application session. | User switching or session termination immediately revokes context (`STALE_AUTHORIZATION`). |
| **Restart Never Auto-Authorizes** | Application restart restores user identity, but never active tokens. | No persistent privileged tokens; fresh authorization required. |
| **Security Failure $\neq$ ECU Fault** | An access denial is an application security event, not a defect. | `is_security_error=True`, `is_communication_failure=False`, `is_diagnostic_fault=False`. |
| **AI / Reasoning Containment** | AI suggestions are untrusted inputs. | `validate_ai_recommendation` blocks raw command strings (`04`, `2E`, `2F`, `34`). |
| **Admin Boundary** | ADMIN role does NOT permit destructive ECU commands. | Prohibited services (`04`, `14`, `2E`, `27`, `2F`, `34-37`) remain blocked by safety gate. |
| **Privacy & Zero Secret Leakage** | No hardcoded credentials; no secrets in logs or reports. | Sanity checked; zero passwords, tokens, or keys in serialized artifacts. |
| **Persistence Authority** | Storage operations route via J-3 repository. | `security_audit_events` collection in `DiagnosticRepository`. |

---

## 2. Canonical Authorization Model

### A. Role Taxonomy
Seyyanen defines four non-overlapping diagnostic roles:
1. **`VIEWER`**: Passive read-only observation. Can view telemetry, read DTCs, view live PIDs, and export reports.
2. **`TECHNICIAN`**: Standard diagnostic operations. Viewer permissions plus starting diagnostic sessions, running read-only tests, and executing guided procedure steps.
3. **`ADVANCED_TECHNICIAN`**: Diagnostic specialist. Technician permissions plus advanced ECU services, actuator control tests, and DTC clearing (subject to diagnostic safety approval).
4. **`ADMIN`**: Platform administrator. User management, diagnostic configuration, and security policy management. Does **NOT** grant arbitrary ECU destructive commands.

### B. Permission Taxonomy
- `VIEW_DIAGNOSTIC_DATA`
- `START_DIAGNOSTIC_SESSION`
- `READ_DTC`
- `READ_LIVE_DATA`
- `RUN_READ_ONLY_TEST`
- `RUN_GUIDED_TEST`
- `RUN_ADVANCED_SERVICE`
- `RUN_ACTUATOR_TEST`
- `WRITE_ECU`
- `CLEAR_DTC`
- `MODIFY_CONFIGURATION`
- `MANAGE_USERS`
- `MANAGE_SECURITY_POLICY`
- `EXPORT_DIAGNOSTIC_REPORT`

### C. Operation Risk Classification
- **`READ_ONLY`**: `read_dtc`, `read_live_data`, `read_pid`, `read_did`, `view_diagnostic_data`, `export_diagnostic_report`.
- **`DIAGNOSTIC_ACTION`**: `start_diagnostic_session`, `run_read_only_test`, `run_guided_test`, `run_advanced_service`.
- **`PRIVILEGED`**: `run_actuator_test`, `clear_dtc`, `modify_configuration`, `manage_users`, `manage_security_policy`.
- **`HIGHLY_PRIVILEGED`**: `write_ecu`.

---

## 3. Double-Gate Architecture (Security + Diagnostic Safety)

Automotive diagnostics involves physical vehicle hardware where a software instruction can actuate valves, cycle injectors, or overwrite flash memory. User permission alone is necessary but **never sufficient**.

```
                           User / Client Request
                                     │
                                     ▼
                      ┌─────────────────────────────┐
                      │    Gate 1: Authorization    │
                      │  (User Role, Permissions,   │
                      │   Resource Scope, Session)  │
                      └──────────────┬──────────────┘
                                     │
                              PASS   │   DENY
                        ┌────────────┴────────────┐
                        ▼                         ▼
         ┌─────────────────────────────┐   Blocked by J-5
         │ Gate 2: Diagnostic Safety   │   (AuthorizationDeniedError)
         │  (ServiceSafetyPolicy, G-1, │
         │   Prohibited Services 0x04) │
         └──────────────┬──────────────┘
                        │
                 PASS   │   DENY
           ┌────────────┴────────────┐
           ▼                         ▼
     Dispatched to Adapter     Blocked by Safety
     (J-1 / Transport)         (SAFETY_POLICY_DENIED)
```

### Safety Denial Example:
When an `ADVANCED_TECHNICIAN` requests operation `clear_dtc`:
1. **Gate 1 (Authorization)**: User has `Role.ADVANCED_TECHNICIAN` $\rightarrow$ `CLEAR_DTC` permission is granted $\rightarrow$ **PASS**.
2. **Gate 2 (Diagnostic Safety)**: Service is Mode `04` / UDS `0x14`. `ServiceSafetyPolicy` enforces `allow_non_readonly=False` $\rightarrow$ Mode 04 is prohibited $\rightarrow$ **DENY**.
3. **Result**: Operation is **BLOCKED** with reason `SAFETY_POLICY_DENIED`. Even with elevated user roles, diagnostic safety cannot be bypassed.

---

## 4. Resource Scoping & Session Isolation

Permissions are strictly scoped to physical resources:
- **Vehicle Scope (`vehicle:{vin}`)**: An authorization context targeting `vehicle:WAUZZZ123` cannot be used on `vehicle:WAUZZZ999`.
- **ECU Scope (`ecu:{target_ecu}`)**: An authorization context targeting `ecu:ECM` cannot be used to command `ecu:TCM`.
- **Session Scope (`session:{id}`)**: Tokens are bound to the active `application_session_id`.
- **User Switching Hook**: When J-4 switches active users, `SecurityManager.handle_user_switched` invalidates previous session tokens, preventing stale privilege leakage.

---

## 5. Untrusted AI & Automated Workflow Containment

- **AI Containment**: Any string output from an LLM or reasoning engine attempting raw service dispatches (e.g. `"04"`, `"2E 01 02"`, `"34"`) immediately raises `SecurityPolicyViolationError` (`UNTRUSTED_AI_COMMAND`).
- **Workflow Containment**: Automated workflows run strictly under the supplied session context. An automated workflow cannot self-elevate to `Role.ADMIN` or grant itself unassigned permissions.

---

## 6. Structured Security Audit Trail

All authorization decisions (both `ALLOW` and `DENY`) emit structured `SecurityAuditEvent` instances persisted to J-3:
- Event Types:
  - `AUTHORIZATION_ALLOWED`
  - `AUTHORIZATION_DENIED`
  - `PRIVILEGED_OPERATION_REQUESTED`
  - `PRIVILEGED_OPERATION_BLOCKED`
  - `USER_ROLE_ASSIGNED`
  - `SECURITY_POLICY_CHANGED`
- Audit events contain caller principal, session ID, resource, operation, and timestamp. Zero credentials, passwords, or tokens are logged.

---

## 7. Verification & Attack-Style Test Matrix (`test_phase_j5.py`)

The test suite in `test_phase_j5.py` executed 33 tests with zero warnings under `python -W error`:

| Section | Test Description | Result |
| :--- | :--- | :--- |
| **A** | Permission model definition and operation-to-permission mapping | **PASS** |
| **B** | Role model hierarchy and role taxonomy validation | **PASS** |
| **C** | Default-deny enforcement on unregistered operations | **PASS** |
| **D** | Unknown permission rejection | **PASS** |
| **E** | Unknown operation rejection | **PASS** |
| **F** | Unknown/unregistered user rejection | **PASS** |
| **G** | Missing authorization context (`None`) handling | **PASS** |
| **H** | Allowed read-only operation for Viewer / Technician | **PASS** |
| **I** | Denied privileged operation for insufficient role (Viewer attempting clear DTC) | **PASS** |
| **J** | Role-to-permission mapping and role promotion | **PASS** |
| **K** | Resource scoping across distinct vehicle VINs | **PASS** |
| **L** | Vehicle and ECU isolation preventing cross-ECU dispatch | **PASS** |
| **M** | Session binding validation against active application session | **PASS** |
| **N** | User switching invalidation rejecting stale session tokens | **PASS** |
| **O** | Restart/recovery requiring fresh authorization (no persistent privileged tokens) | **PASS** |
| **P** | Security audit event persistence and query retrieval via J-3 repository | **PASS** |
| **Q** | Distinct, explainable denial reasons (`NO_AUTH_CONTEXT`, `UNKNOWN_USER`, etc.) | **PASS** |
| **R** | Double-gate approval when both authorization and safety pass | **PASS** |
| **S** | Safety denial despite authorization approval (destructive Mode 04 blocked) | **PASS** |
| **T** | Authorization denial blocks command before reaching adapter transport | **PASS** |
| **U** | Untrusted AI recommendation containment (blocking raw command strings) | **PASS** |
| **V** | Automated workflow cannot self-elevate permissions or assign roles | **PASS** |
| **W** | H-2 automated test sequencer integration | **PASS** |
| **X** | G-1 advanced ECU services integration | **PASS** |
| **Y** | J-1 diagnostic adapter prohibited services hardware gating | **PASS** |
| **Z** | J-4 user/session manager identity integration | **PASS** |
| **AA** | J-3 persistence round-trip through SQLite and In-Memory storage engines | **PASS** |
| **AB** | Secret leakage verification: zero passwords, tokens, or keys in serialized data | **PASS** |
| **AC** | Malformed authorization input rejection | **PASS** |
| **AD** | Policy version handling | **PASS** |
| **AE** | Policy change authorization requiring admin permissions | **PASS** |
| **AF** | Concurrent application session isolation across multiple managers | **PASS** |
| **AG** | Full cross-layer regression and invariant verification | **PASS** |

---

## 8. Known Limitations & Transition to Phase J-6

1. **Local Authentication**: J-5 establishes authorization boundaries and local role assignments. Full credential verification (e.g. hashed password checks, WebAuthn, or biometric login) can be plugged into the `Principal` model if required.
2. **Offline-First Scoping**: Policy definitions are stored locally. Enterprise multi-tenant IAM (e.g. OAuth2/OIDC token exchange) is not required for standalone offline diagnostic tools.
3. **Double-Gate Non-Bypassable**: Diagnostic safety takes precedence over all authorization grants. Even `ADMIN` users cannot override hard-coded service safety prohibitions.
