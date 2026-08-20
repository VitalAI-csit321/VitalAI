from datetime import date

import pytest

from app.models.patient import Gender
from scripts.seed_demo_patients import _field, _gender_from_form, _parse_folder

_SAMPLE_REG_FORM = """Patient Registration Form

Name: Aaron Huff
DOB: 1970-03-31
Gender: Male
Phone: 0400 000 000
Email: aaron.huff@example.org
Address: 1 Example St, Sydney, NSW, 2000

Medicare number: 4291 81860/6
IHI: 8003000000000000
Concession card: None
"""


def test_parse_folder_splits_name_and_uuid() -> None:
    name, patient_id = _parse_folder("Aaron_Huff_5bff524f-cbb8-44fa-8b20-fc79352ada8e")
    assert name == "Aaron Huff"
    assert str(patient_id) == "5bff524f-cbb8-44fa-8b20-fc79352ada8e"


def test_field_extracts_dob_and_mrn() -> None:
    assert _field(_SAMPLE_REG_FORM, "DOB") == "1970-03-31"
    assert date.fromisoformat(_field(_SAMPLE_REG_FORM, "DOB")) == date(1970, 3, 31)
    assert _field(_SAMPLE_REG_FORM, "Medicare number") == "4291 81860/6"


def test_gender_from_form_reads_real_field() -> None:
    assert _gender_from_form(_SAMPLE_REG_FORM) == Gender.MALE
    assert _gender_from_form(_SAMPLE_REG_FORM.replace("Male", "Female")) == Gender.FEMALE


def test_gender_from_form_rejects_unrecognised_value() -> None:
    with pytest.raises(ValueError, match="unrecognised gender"):
        _gender_from_form(_SAMPLE_REG_FORM.replace("Gender: Male", "Gender: Unspecified"))
