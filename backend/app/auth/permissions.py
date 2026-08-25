"""Permission model for VitalAI RBAC.

See 'VitalAI RBAC Report - Audit Trail.md' (repo root) for the authoritative
spec. Route handlers gate on permissions via require_permission()
(app/auth/dependencies.py), never on UserRole directly. The sole documented
exception is app/routes/llm.py, infra/ops diagnostics outside this taxonomy.
"""

from app.models.user import User, UserRole

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
REGISTER_PATIENT = "register_patient"
VIEW_ALL_QUEUES = "view_all_queues"

ROLE_PERMISSIONS: dict[UserRole, set[str]] = {
    UserRole.FRONT_DESK: {
        VIEW_QUEUE,
        CAPTURE_CONSENT,
        VIEW_RECORDS_GENERAL,
        UPLOAD_GENERAL,
        MANAGE_APPOINTMENTS_ALL,
        REGISTER_PATIENT,
    },
    UserRole.OPERATOR: {
        VIEW_QUEUE,
        MANAGE_CASES,
        APPROVE_ACTION,
        CAPTURE_CONSENT,
        VIEW_RECORDS_GENERAL,
        UPLOAD_GENERAL,
        UPLOAD_CLINICAL,
        ASSIGN_PATIENTS,
        MANAGE_APPOINTMENTS_ALL,
        REGISTER_PATIENT,
    },
    UserRole.ADMIN: {
        VIEW_QUEUE,
        MANAGE_CASES,
        APPROVE_ACTION,
        CAPTURE_CONSENT,
        VIEW_RECORDS_GENERAL,
        UPLOAD_GENERAL,
        UPLOAD_CLINICAL,
        ASSIGN_PATIENTS,
        MANAGE_APPOINTMENTS_ALL,
        MANAGE_USERS,
        CONFIGURE_GOVERNANCE,
        READ_AUDIT,
        REGISTER_PATIENT,
        VIEW_ALL_QUEUES,
    },
    UserRole.DOCTOR: {
        VIEW_CLINICAL,
        VIEW_RECORDS_GENERAL,
        MANAGE_OWN_CALENDAR,
    },
}

GRANTABLE: dict[UserRole, set[str]] = {
    UserRole.OPERATOR: {READ_AUDIT, VIEW_CLINICAL},
    UserRole.ADMIN: {VIEW_CLINICAL},
}


def effective_permissions(user: User) -> set[str]:
    base = ROLE_PERMISSIONS[user.role]
    allowed = GRANTABLE.get(user.role, set())
    granted = {p for p in user.granted_permissions if p in allowed}
    return base | granted
