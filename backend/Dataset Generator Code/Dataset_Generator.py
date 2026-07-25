from dataclasses import dataclass
from pathlib import Path
from faker import Faker
import random
import uuid

fake = Faker("en_AU")

CHIEF_COMPLAINTS = [
    "Headache and fatigue.",
    "Persistent cough and sore throat.",
    "Lower back pain after lifting.",
    "Shortness of breath on exertion.",
    "Abdominal pain and nausea.",
    "Skin rash on both forearms.",
    "Dizziness and occasional palpitations.",
    "Joint pain in the knees.",
    "Fever and chills for two days.",
    "Anxiety and difficulty sleeping.",
]

ASSESSMENTS = [
    "Likely viral infection.",
    "Consistent with musculoskeletal strain.",
    "Probable seasonal allergic reaction.",
    "Signs suggestive of mild hypertension.",
    "Likely gastro-oesophageal reflux.",
    "Consistent with tension-type headache.",
    "Probable upper respiratory tract infection.",
    "Signs suggestive of mild anxiety disorder.",
    "Likely soft tissue inflammation.",
    "No acute findings on examination.",
]

PLAN_ITEMS = [
    "Rest",
    "Increase fluid intake",
    "Follow up in one week",
    "Refer for physiotherapy",
    "Order blood tests",
    "Prescribe symptomatic relief",
    "Monitor blood pressure at home",
    "Refer to specialist if symptoms persist",
    "Advise on dietary changes",
    "Arrange follow-up imaging",
]

MEDICATIONS = [
    {
        "name": "Paracetamol 500mg",
        "directions": "Take 2 tablets every 6 hours as needed.",
    },
    {
        "name": "Amoxicillin 500mg",
        "directions": "Take 1 capsule three times a day for 7 days.",
    },
    {
        "name": "Ibuprofen 400mg",
        "directions": "Take 1 tablet every 8 hours with food as needed.",
    },
    {
        "name": "Cetirizine 10mg",
        "directions": "Take 1 tablet once daily.",
    },
    {
        "name": "Omeprazole 20mg",
        "directions": "Take 1 capsule once daily before breakfast.",
    },
    {
        "name": "Salbutamol Inhaler 100mcg",
        "directions": "Inhale 2 puffs as needed for shortness of breath.",
    },
    {
        "name": "Metformin 500mg",
        "directions": "Take 1 tablet twice daily with meals.",
    },
]

APPOINTMENT_TYPES = [
    "General Consultation",
    "Vaccination",
    "Blood Test",
    "Follow-up Review",
    "Physiotherapy Session",
    "Specialist Referral",
    "Minor Procedure",
    "Health Check",
]


@dataclass
class Patient:
    patient_id: str
    first_name: str
    last_name: str
    dob: str
    gender: str
    phone: str
    email: str
    address: str
    medicare_number: str


class DatasetGenerator:
    def __init__(self, output_dir: str = "dataset"):
        self.output_dir = Path(output_dir)

    # ----------------------------
    # Patient Generation
    # ----------------------------
    def generate_patient(self) -> Patient:
        return Patient(
            patient_id=str(uuid.uuid4()),
            first_name=fake.first_name(),
            last_name=fake.last_name(),
            dob=str(
                fake.date_of_birth(
                    minimum_age=0,
                    maximum_age=100
                )
            ),
            gender=random.choice(["Male", "Female"]),
            phone=fake.phone_number(),
            email=fake.email(),
            address=fake.address().replace("\n", ", "),
            medicare_number=str(
                random.randint(
                    1000000000,
                    9999999999
                )
            )
        )

    # ----------------------------
    # Document Templates
    # ----------------------------
    def consultation_note(self, patient: Patient):
        complaint = random.choice(CHIEF_COMPLAINTS)
        assessment = random.choice(ASSESSMENTS)
        plan_items = random.sample(
            PLAN_ITEMS, k=random.randint(2, 4)
        )
        plan = "\n".join(f"- {item}" for item in plan_items)

        return f"""
Patient: {patient.first_name} {patient.last_name}
DOB: {patient.dob}

Chief Complaint:
{complaint}

Assessment:
{assessment}

Plan:
{plan}
"""

    def prescription(self, patient: Patient):
        medication = random.choice(MEDICATIONS)

        return f"""
Prescription

Patient:
{patient.first_name} {patient.last_name}

Medication:
{medication['name']}

Directions:
{medication['directions']}
"""

    def pathology_report(self, patient: Patient):
        haemoglobin = round(
            random.uniform(100, 180), 1
        )

        if haemoglobin < 120:
            interpretation = "Low. Recommend clinical correlation."
        elif haemoglobin > 160:
            interpretation = "High. Recommend clinical correlation."
        else:
            interpretation = "Normal."

        return f"""
Pathology Report

Patient:
{patient.first_name} {patient.last_name}

Haemoglobin:
{haemoglobin} g/L

Interpretation:
{interpretation}
"""

    def registration_form(self, patient: Patient):
        return f"""
Patient Registration Form

Name:
{patient.first_name} {patient.last_name}

DOB:
{patient.dob}

Phone:
{patient.phone}

Email:
{patient.email}

Address:
{patient.address}

Medicare:
{patient.medicare_number}
"""

    def appointment_history(self, patient: Patient):
        num_appointments = random.randint(2, 5)

        appointments = sorted(
            fake.date_between(start_date="-2y", end_date="today")
            for _ in range(num_appointments)
        )

        lines = "\n".join(
            f"{date.strftime('%d/%m/%Y')} - {random.choice(APPOINTMENT_TYPES)}"
            for date in appointments
        )

        return f"""
Appointment History

{lines}
"""

    # ----------------------------
    # File Handling
    # ----------------------------
    def create_patient_directories(
        self,
        patient: Patient
    ):
        patient_folder = (
            self.output_dir
            / f"{patient.first_name}_{patient.last_name}_{patient.patient_id}"
        )

        clinical_folder = (
            patient_folder / "Clinical_Docs"
        )

        admin_folder = (
            patient_folder / "Admin_Docs"
        )

        clinical_folder.mkdir(
            parents=True,
            exist_ok=True
        )

        admin_folder.mkdir(
            parents=True,
            exist_ok=True
        )

        return clinical_folder, admin_folder

    def save_document(
        self,
        folder: Path,
        filename: str,
        content: str
    ):
        file_path = folder / filename

        with open(
            file_path,
            "w",
            encoding="utf-8"
        ) as f:
            f.write(content)

    # ----------------------------
    # Dataset Generation
    # ----------------------------
    def generate_dataset(
        self,
        num_patients: int
    ):
        for _ in range(num_patients):
            patient = self.generate_patient()

            clinical, admin = (
                self.create_patient_directories(
                    patient
                )
            )

            self.save_document(
                clinical,
                "consultation.txt",
                self.consultation_note(patient)
            )

            self.save_document(
                clinical,
                "prescription.txt",
                self.prescription(patient)
            )

            self.save_document(
                clinical,
                "pathology_report.txt",
                self.pathology_report(patient)
            )

            self.save_document(
                admin,
                "registration_form.txt",
                self.registration_form(patient)
            )

            self.save_document(
                admin,
                "appointment_history.txt",
                self.appointment_history(patient)
            )

        print(
            f"Dataset generated in: {self.output_dir}"
        )

