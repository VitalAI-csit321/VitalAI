"""Category -> target role resolver (FR-TRIAGE-01 / FR-GOV-02).

Canonical mapping from the 10-category taxonomy
(docs/superpowers/specs/2026-07-20-ai-task-routing-design.md section 12) to
the role whose queue a task lands in. Same shape as
app/services/routing_rules.py::decide(): a pure function, no DB, no I/O.
Categories map directly to a role per the locked table — no permission-walk
algorithm, per section 12's explicit supersession of the earlier design's
section 5.
"""

import enum

from app.models.user import UserRole


class TaskCategory(enum.StrEnum):
    APPOINTMENT_REQUEST = "appointment_request"
    NEW_PATIENT_ONBOARDING = "new_patient_onboarding"
    PRESCRIPTION_RENEWAL = "prescription_renewal"
    RESULTS_ENQUIRY = "results_enquiry"
    REFERRAL_REQUEST = "referral_request"
    MEDICAL_RECORDS_REQUEST = "medical_records_request"
    BILLING_INSURANCE_ENQUIRY = "billing_insurance_enquiry"
    COMPLAINT_ESCALATION = "complaint_escalation"
    GENERAL_ADMINISTRATIVE = "general_administrative"
    URGENT_EMERGENCY = "urgent_emergency"


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

    Pure function of the category table in
    docs/superpowers/specs/2026-07-20-ai-task-routing-design.md section 12.
    """
    return _CATEGORY_TO_ROLE[category]
