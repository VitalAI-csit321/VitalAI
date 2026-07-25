import pytest

from app.models.user import UserRole
from app.services.task_routing_rules import TaskCategory, resolve_target_role


@pytest.mark.parametrize(
    "category,expected_role",
    [
        (TaskCategory.APPOINTMENT_REQUEST, UserRole.FRONT_DESK),
        (TaskCategory.NEW_PATIENT_ONBOARDING, UserRole.FRONT_DESK),
        (TaskCategory.PRESCRIPTION_RENEWAL, UserRole.DOCTOR),
        (TaskCategory.RESULTS_ENQUIRY, UserRole.DOCTOR),
        (TaskCategory.REFERRAL_REQUEST, UserRole.OPERATOR),
        (TaskCategory.MEDICAL_RECORDS_REQUEST, UserRole.OPERATOR),
        (TaskCategory.BILLING_INSURANCE_ENQUIRY, UserRole.FRONT_DESK),
        (TaskCategory.COMPLAINT_ESCALATION, UserRole.OPERATOR),
        (TaskCategory.GENERAL_ADMINISTRATIVE, UserRole.FRONT_DESK),
        (TaskCategory.URGENT_EMERGENCY, UserRole.OPERATOR),
    ],
)
def test_resolve_target_role(category, expected_role):
    assert resolve_target_role(category) == expected_role


def test_all_ten_categories_covered():
    """Every TaskCategory value must resolve; a KeyError here means the
    table fell out of sync with the enum."""
    for category in TaskCategory:
        assert resolve_target_role(category) in UserRole
