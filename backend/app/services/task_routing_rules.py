"""Category -> target role resolver (FR-TRIAGE-01 / FR-GOV-02).

Canonical mapping from the 10-category taxonomy
(docs/superpowers/specs/2026-07-20-ai-task-routing-design.md section 12) to
the role whose queue a task lands in. Same shape as
app/services/routing_rules.py::decide(): a pure function, no DB, no I/O.
Categories map directly to a role per the locked table; no permission-walk
algorithm, per section 12's explicit supersession of the earlier design's
section 5.
"""

from app.models.task import TaskCategory
from app.models.user import UserRole  # noqa: F401

_CATEGORY_TO_ROLE: dict[TaskCategory, UserRole] = {
    TaskCategory.APPOINTMENT_REQUEST: UserRole.FRONT_DESK,
    TaskCategory.NEW_PATIENT_ONBOARDING: UserRole.FRONT_DESK,
    TaskCategory.PRESCRIPTION_RENEWAL: UserRole.DOCTOR,
    TaskCategory.RESULTS_ENQUIRY: UserRole.DOCTOR,
    TaskCategory.REFERRAL_REQUEST: UserRole.OPERATOR,
    TaskCategory.MEDICAL_RECORDS_REQUEST: UserRole.OPERATOR,
    TaskCategory.BILLING_INSURANCE_ENQUIRY: UserRole.FRONT_DESK,
    TaskCategory.COMPLAINT_ESCALATION: UserRole.OPERATOR,
    TaskCategory.GENERAL_ADMINISTRATIVE: UserRole.FRONT_DESK,
    TaskCategory.URGENT_EMERGENCY: UserRole.OPERATOR,
}


def resolve_target_role(category: TaskCategory) -> UserRole:
    """Map a task category to the role whose queue it lands in.

    The built-in table above is the default. An admin-configured override in
    settings.task_routing_category_roles wins for the categories it names; a
    value that is not a real role is ignored rather than raising, because a bad
    row must never take routing down.
    """
    from app.config import settings

    override = settings.task_routing_category_roles.get(category.value)
    if override is not None:
        try:
            return UserRole(override)
        except ValueError:
            pass
    return _CATEGORY_TO_ROLE[category]
