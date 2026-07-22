# RBAC Phase 1: Role & Permission Foundation

## Problem

`VitalAI RBAC Report - Audit Trail.md` is the finalized-for-A4 access model: NIST Core
RBAC with per-user permission grants and row-level scoping. None of it exists in the
backend today — `UserRole` has 3 values (no `DOCTOR`), route handlers gate on
`require_roles()` (raw role membership) rather than permissions, there is no grant
mechanism, and two routes (`consent.py`, `routing.py`) have no gating at all beyond
"is logged in."

This is phase 1 of a 6-phase rollout (see `WORKLOG.md` for the full phase list and
dependency order). This phase builds the permission-checking mechanism itself —
roles, permission constants, the grants table, and every existing route migrated onto
it — since `effective_permissions()` is defined in terms of granted permissions and a
permission system without a working grant mechanism is only half real. Later phases
(Patients, Doctor-Patient Assignments + RAG query route, Appointments routes, Users
endpoint, Audit access gating) all depend on this one and are out of scope here.

Explicitly out of scope for this phase (and this rollout in general, per direction
from Amin): the clinical upload/ingestion API (spec section 8) — clinical content
continues to be ingested manually via `scripts/ingest_corpus.py`, not through a new
upload endpoint.

## Design

### 1. Roles

`app/models/user.py`: `UserRole` gains `DOCTOR`; `OPS_MANAGER` is renamed to
`OPERATOR`. Every code reference to `UserRole.OPS_MANAGER` is updated in the same
change (`app/routes/intake.py`, `app/routes/llm.py`, plus 3 test files).

### 2. Permissions

New `app/auth/permissions.py`:

```python
VIEW_QUEUE = "view_queue"
MANAGE_CASES = "manage_cases"
APPROVE_ACTION = "approve_action"
CAPTURE_CONSENT = "capture_consent"
VIEW_RECORDS_GENERAL = "view_records_general"
UPLOAD_GENERAL = "upload_general"
UPLOAD_CLINICAL = "upload_clinical"
VIEW_CLINICAL = "view_clinical"
ASSIGN_PATIENTS = "assign_patients"
MANAGE_APPOINTMENTS_ALL = "manage_appointments_all"
MANAGE_OWN_CALENDAR = "manage_own_calendar"
MANAGE_USERS = "manage_users"
CONFIGURE_GOVERNANCE = "configure_governance"
READ_AUDIT = "read_audit"

ROLE_PERMISSIONS: dict[UserRole, set[str]]   # verbatim from the RBAC report, section 4
GRANTABLE: dict[UserRole, set[str]]          # verbatim from the RBAC report, section 5

def effective_permissions(user: User) -> set[str]:
    base = ROLE_PERMISSIONS[user.role]
    allowed = GRANTABLE.get(user.role, set())
    granted = {p for p in user.granted_permissions if p in allowed}
    return base | granted
```

`UPLOAD_CLINICAL` and `VIEW_CLINICAL` are defined now (per the report's fixed
taxonomy) even though nothing exercises them until later phases — no dead-code
concern, they're part of `ROLE_PERMISSIONS` from day one.

### 3. Grants

New `app/models/permission_grant.py`:

```python
class UserPermissionGrant(Base):
    __tablename__ = "user_permission_grants"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    permission: Mapped[str] = mapped_column(String(50), primary_key=True)
    granted_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
```

Registered in `app/models/__init__.py.__all__` and actually imported there — the
appointments table shipped as an orphaned stub once already (listed in `__all__` but
never imported, so it never registered with `Base.metadata`); not repeating that.

`User` (`app/models/user.py`) gains:

```python
permission_grants: Mapped[list["UserPermissionGrant"]] = relationship(
    "UserPermissionGrant",
    foreign_keys="UserPermissionGrant.user_id",
    lazy="selectin",
)
granted_permissions = association_proxy("permission_grants", "permission")
```

**Why `lazy="selectin"`, not the SQLAlchemy default:** the default lazy-load strategy
triggers a synchronous DB call on attribute access, which raises `MissingGreenlet`
under async SQLAlchemy unless it happens inside an already-awaited context.
`selectin` issues its own eager `SELECT` as part of the initial user fetch instead, so
`effective_permissions()` can stay a plain synchronous function — exactly the report's
signature — without the caller having to know to eager-load first. This is the
standard safe pattern for relationships accessed outside the immediate query in async
SQLAlchemy, not a one-off workaround.

### 4. Enforcement

`app/auth/dependencies.py` gains:

```python
def require_permission(permission: str):
    def dep(current_user: User = Depends(get_current_user)) -> User:
        if permission not in effective_permissions(current_user):
            raise HTTPException(status_code=403, detail=f"Missing required permission: {permission}")
        return current_user
    return dep
```

`require_roles()` is kept, but only for one documented exception: `app/routes/llm.py`
(LLM provider ping/status). This is infra/ops diagnostics, not clinical or patient
data, and doesn't map to anything in the report's 14-permission taxonomy. Force-fitting
it to e.g. `CONFIGURE_GOVERNANCE` (admin-only) would silently drop the operator access
it has today. One narrow, commented exception is preferable to inventing a permission
the spec doesn't define. Every other `require_roles()` call site is removed.

### 5. Route migration

| Route | Today | Becomes |
|---|---|---|
| `PATCH /intake/{id}/status` | `require_roles(OPS_MANAGER, ADMIN)` | `require_permission(MANAGE_CASES)` |
| `POST /auth/users/{id}/elevate` | `require_roles(ADMIN)` | `require_permission(MANAGE_USERS)` |
| `GET /audit/by-case/{id}` | `require_roles(ADMIN)` | `require_permission(READ_AUDIT)` |
| `POST /consent`, `POST /consent/{id}/capture`, `POST /consent/{id}/withdraw` | ungated (any authenticated user) | `require_permission(CAPTURE_CONSENT)` |
| `GET /consent/by-case/{id}` | ungated | `require_permission(VIEW_RECORDS_GENERAL)` |
| `POST /routing` | ungated | `require_permission(MANAGE_CASES)` |
| `GET /routing/by-case/{id}` | ungated | `require_permission(VIEW_QUEUE)` |
| `POST /intake`, `GET /intake/{id}` | ungated | staying ungated — no permission in the report's list cleanly covers "create/view a case" |
| `GET/POST /llm/*` | `require_roles(ADMIN, OPS_MANAGER)` | unchanged (documented exception, see above) |

Doctor row-level filtering (e.g. a doctor only seeing consent/routing data for
assigned patients) is explicitly deferred to the Doctor-Patient Assignments phase —
this phase only adds the permission check, not the row-level filter, since the
assignment table doesn't exist yet.

### 6. Grant/revoke endpoints

New, in `app/routes/auth.py` next to the existing `elevate` endpoint:

- `POST /auth/users/{user_id}/grants` — body `{"permission": str}`. Gated on
  `MANAGE_USERS`. Validates `permission in GRANTABLE.get(target.role, set())`; 422 if
  not grantable to that role (e.g. `READ_AUDIT` to a `FRONT_DESK` user), 404 if the
  target user doesn't exist, 409 if already granted. Writes an audit event
  `user.permission_granted` (dot-namespaced, matching the convention already decided
  in `docs/backend_gap_analysis.md`'s audit section).
- `DELETE /auth/users/{user_id}/grants/{permission}` — same gating. 404 if the grant
  doesn't exist. Writes `user.permission_revoked`.

### 7. Migration

One Alembic revision, `down_revision = "0007"`:

```sql
ALTER TYPE user_role RENAME VALUE 'ops_manager' TO 'operator';
ALTER TYPE user_role ADD VALUE 'doctor';
```

Both are transaction-safe on Postgres 12+ (already on `pg16`) since nothing in this
migration *uses* the new value in the same transaction. Plus a standard
`op.create_table` for `user_permission_grants`.

Postgres cannot drop an enum value, so `downgrade()` can reverse the rename but cannot
cleanly remove `doctor` without recreating the type. Per direction from Amin (dataset
is small, DB can be recreated if needed), this is accepted as a documented,
intentional one-way limitation rather than engineered around — matches the report's
own stance that removing enum values is "the disproportionate operation."

## Testing

- Pure unit tests for `effective_permissions()` / `ROLE_PERMISSIONS` / `GRANTABLE` —
  no DB required.
- Migration upgrade/downgrade/upgrade round-trip against real Postgres (same pattern
  used to verify migration `0007`).
- Route-level tests added to the existing per-route test files
  (`test_auth.py`, `test_consent.py`, `test_triage_routing.py`, `test_audit.py`,
  `test_intake.py`): 403 on missing permission, success on correct permission/grant,
  for every row in the route migration table above.
- Grant/revoke endpoint tests: 422 on non-grantable permission, 409 on duplicate
  grant, 404 on missing user/grant, and an audit-event-written assertion for both
  grant and revoke.

## Explicitly out of scope (this phase)

- Clinical upload/ingestion API (report section 8) — stays manual.
- Doctor-patient assignments, row-level scoping, RAG query route wiring — next phase,
  blocked on the Patients table.
- Patients table, appointments routes, `GET /users`, audit-log-read logging — later
  phases per the dependency order in `WORKLOG.md`.
- `AUDITOR`/`COMPLIANCE` roles, MFA, image-PDF/OCR, `sensitive` access scope — all
  explicitly deferred by the report itself (section 14).