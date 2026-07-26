from datetime import date

from app.models.patient import Gender
from scripts.seed_demo_patients import _field, _gender_for, _parse_folder

_SAMPLE_REG_FORM = """
Patient Registration Form

Name:
Aaron Huff

DOB:
1970-03-31

Medicare:
4291818606
"""


def test_parse_folder_splits_name_and_uuid() -> None:
    name, patient_id = _parse_folder("Aaron_Huff_5bff524f-cbb8-44fa-8b20-fc79352ada8e")
    assert name == "Aaron Huff"
    assert str(patient_id) == "5bff524f-cbb8-44fa-8b20-fc79352ada8e"


def test_field_extracts_dob_and_mrn() -> None:
    assert _field(_SAMPLE_REG_FORM, "DOB") == "1970-03-31"
    assert date.fromisoformat(_field(_SAMPLE_REG_FORM, "DOB")) == date(1970, 3, 31)
    assert _field(_SAMPLE_REG_FORM, "Medicare") == "4291818606"


def test_gender_for_is_deterministic() -> None:
    import uuid

    patient_id = uuid.uuid4()
    assert _gender_for(patient_id) == _gender_for(patient_id)
    assert _gender_for(patient_id) in (Gender.FEMALE, Gender.MALE, Gender.NON_BINARY)
