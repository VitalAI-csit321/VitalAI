import argparse
import json
import random
import re
import uuid
from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path

from faker import Faker

fake = Faker("en_AU")

# ----------------------------
# Doctor roster, matched to VitalAI's locked RBAC directory.
# note_style gives each doctor a consistent, distinct documentation habit,
# instead of every note reading like the same author.
# ----------------------------
DOCTORS = [
    {"name": "Dr Aisha Rahman", "id": "doctor01", "specialty": "womens_health", "note_style": "prose"},
    {"name": "Dr David Nguyen", "id": "doctor02", "specialty": "chronic_disease", "note_style": "soap"},
    {"name": "Dr Priya Menon", "id": "doctor03", "specialty": "mental_health", "note_style": "prose"},
    {"name": "Dr Marcus O'Connell", "id": "doctor04", "specialty": "mens_health", "note_style": "terse"},
    {"name": "Dr Hannah Fitzgerald", "id": "doctor05", "specialty": "paediatrics", "note_style": "prose"},
    {"name": "Dr Samuel Osei", "id": "doctor06", "specialty": "aged_care", "note_style": "soap"},
]

ALLERGY_POOL = [None] * 7 + ["Penicillin", "Sulfa drugs", "Aspirin (NSAIDs)", "Latex", "Bee stings"]

DRUG_ALLERGY_CONFLICTS = {
    "Penicillin": {"Amoxicillin 500mg"},
    "Sulfa drugs": {"Sulfamethoxazole/Trimethoprim 800/160mg"},
    "Aspirin (NSAIDs)": {"Ibuprofen 400mg"},
}

SMOKING_STATUS = ["Never smoked"] * 5 + ["Former smoker", "Current smoker, 5-10 cigarettes/day"]
ALCOHOL_USE = ["Nil"] * 3 + ["Social, 1-2 standard drinks/week", "Moderate, 5-10 standard drinks/week"]
CONCESSION_TYPES = [None] * 6 + ["Pensioner Concession Card", "Health Care Card", "DVA Gold Card"]
# Real ConsentStatus values (app/models/consent.py) -- CAPTURED/PENDING/WITHDRAWN,
# not the invented CONSENT_VALID/CONSENT_UNCLEAR/CONSENT_INVALID this used to emit.
CONSENT_STATES = ["CAPTURED"] * 17 + ["PENDING"] * 2 + ["WITHDRAWN"] * 1
PHARMACIES = [
    "Priceline Pharmacy Town Hall", "Chemist Warehouse Liverpool St",
    "Sydney CBD Pharmacy", "Amcal Pharmacy George St",
]

DOC_CLASSIFICATION = {
    "registration_form": "Medium",
    "appointment_history": "Low",
    "consultation_note": "High",
    "prescription": "High",
    "pathology_report": "High",
    "referral_letter": "Medium",
    "care_plan": "High",
    "consent_record": "Critical",
    "specialist_letter": "High",
    "hospital_discharge_summary": "High",
    "external_imaging_report": "High",
}

# ----------------------------
# Pathology panels. Real GP-ordered panels return many analytes with
# reference ranges, not one number. Ranges below are typical adult
# reference intervals, not exact lab-specific figures.
# ----------------------------
PATHOLOGY_PANELS = {
    "FBC": [
        {"name": "Haemoglobin", "unit": "g/L", "gender_ranges": {"Male": (130, 180), "Female": (115, 165)}, "decimals": 0},
        {"name": "White Cell Count", "unit": "x10^9/L", "range": (4.0, 11.0), "decimals": 1},
        {"name": "Platelets", "unit": "x10^9/L", "range": (150, 400), "decimals": 0},
        {"name": "Haematocrit", "unit": "L/L", "gender_ranges": {"Male": (0.40, 0.54), "Female": (0.37, 0.47)}, "decimals": 2},
        {"name": "MCV", "unit": "fL", "range": (80, 100), "decimals": 1},
        {"name": "Neutrophils", "unit": "x10^9/L", "range": (2.0, 8.0), "decimals": 1},
        {"name": "Lymphocytes", "unit": "x10^9/L", "range": (1.0, 4.0), "decimals": 1},
    ],
    "UEC": [
        {"name": "Sodium", "unit": "mmol/L", "range": (135, 145), "decimals": 0},
        {"name": "Potassium", "unit": "mmol/L", "range": (3.5, 5.2), "decimals": 1},
        {"name": "Chloride", "unit": "mmol/L", "range": (95, 110), "decimals": 0},
        {"name": "Bicarbonate", "unit": "mmol/L", "range": (22, 32), "decimals": 0},
        {"name": "Urea", "unit": "mmol/L", "range": (2.5, 8.0), "decimals": 1},
        {"name": "Creatinine", "unit": "umol/L", "gender_ranges": {"Male": (60, 110), "Female": (45, 90)}, "decimals": 0},
        {"name": "eGFR", "unit": "mL/min/1.73m2", "range": (60, 120), "decimals": 0},
    ],
    "LFT": [
        {"name": "Total Protein", "unit": "g/L", "range": (60, 80), "decimals": 0},
        {"name": "Albumin", "unit": "g/L", "range": (35, 50), "decimals": 0},
        {"name": "Total Bilirubin", "unit": "umol/L", "range": (2, 20), "decimals": 0},
        {"name": "ALP", "unit": "U/L", "range": (30, 110), "decimals": 0},
        {"name": "GGT", "unit": "U/L", "gender_ranges": {"Male": (5, 50), "Female": (5, 35)}, "decimals": 0},
        {"name": "ALT", "unit": "U/L", "gender_ranges": {"Male": (5, 40), "Female": (5, 30)}, "decimals": 0},
        {"name": "AST", "unit": "U/L", "range": (5, 40), "decimals": 0},
    ],
    "Lipids": [
        {"name": "Total Cholesterol", "unit": "mmol/L", "range": (2.5, 7.5), "decimals": 1},
        {"name": "HDL Cholesterol", "unit": "mmol/L", "gender_ranges": {"Male": (0.7, 2.0), "Female": (0.9, 2.2)}, "decimals": 2},
        {"name": "LDL Cholesterol", "unit": "mmol/L", "range": (1.0, 5.5), "decimals": 1},
        {"name": "Triglycerides", "unit": "mmol/L", "range": (0.3, 3.5), "decimals": 1},
    ],
    "TFT": [
        {"name": "TSH", "unit": "mIU/L", "range": (0.4, 4.0), "decimals": 2},
        {"name": "Free T4", "unit": "pmol/L", "range": (10, 20), "decimals": 1},
    ],
    "Iron Studies": [
        {"name": "Iron", "unit": "umol/L", "range": (6, 32), "decimals": 0},
        {"name": "Transferrin", "unit": "g/L", "range": (2.0, 3.6), "decimals": 1},
        {"name": "Transferrin Saturation", "unit": "%", "range": (10, 50), "decimals": 0},
        {"name": "Ferritin", "unit": "ug/L", "gender_ranges": {"Male": (30, 300), "Female": (13, 150)}, "decimals": 0},
    ],
    "HbA1c_Glucose": [
        {"name": "HbA1c", "unit": "%", "range": (4.5, 11.0), "decimals": 1},
        {"name": "Fasting Glucose", "unit": "mmol/L", "range": (3.5, 15.0), "decimals": 1},
    ],
    "CRP": [
        {"name": "C-Reactive Protein", "unit": "mg/L", "range": (0, 60), "decimals": 0},
    ],
}

LOW_BIAS_ANALYTES = {"Haemoglobin", "Iron", "Ferritin", "Transferrin Saturation"}


def _range_for(patient, spec):
    if "gender_ranges" in spec:
        return spec["gender_ranges"].get(patient.gender, spec["gender_ranges"]["Male"])
    return spec["range"]


def sample_analyte(patient, spec, bias=None, incidental_chance=0.10):
    lo, hi = _range_for(patient, spec)
    span = hi - lo
    if bias == "high":
        value = random.uniform(hi * 1.05, hi * 1.6)
    elif bias == "low":
        value = random.uniform(max(lo * 0.4, 0), lo * 0.95)
    elif random.random() < incidental_chance:
        value = random.uniform(max(lo - span * 0.35, 0), lo) if random.random() < 0.5 else random.uniform(hi, hi + span * 0.35)
    else:
        value = random.uniform(lo, hi)
    value = round(value, spec["decimals"])
    if spec["decimals"] == 0:
        value = int(value)
    flag = "H" if value > hi else ("L" if value < lo else "-")
    return value, flag, lo, hi


def render_panel(patient, panel_name, bias_analytes=None):
    bias_analytes = bias_analytes or []
    rows = []
    flagged = False
    for spec in PATHOLOGY_PANELS[panel_name]:
        bias = None
        if spec["name"] in bias_analytes:
            bias = "low" if (panel_name in ("FBC", "Iron Studies") and spec["name"] in LOW_BIAS_ANALYTES) else "high"
        value, flag, lo, hi = sample_analyte(patient, spec, bias=bias)
        if bias and flag != "-":
            flagged = True
        rows.append((spec["name"], value, spec["unit"], f"{lo}-{hi}", flag))
    return rows, flagged


def format_panel_table(rows):
    name_w = max(len(r[0]) for r in rows) + 2
    header = f"{'Test'.ljust(name_w)}{'Result'.ljust(10)}{'Unit'.ljust(14)}{'Ref Range'.ljust(14)}Flag"
    lines = [header]
    for name, value, unit, ref, flag in rows:
        lines.append(f"{name.ljust(name_w)}{str(value).ljust(10)}{unit.ljust(14)}{ref.ljust(14)}{flag}")
    return "\n".join(lines)


def should_run_panels(archetype, i, num_visits):
    panels = archetype["pathology_panels"]
    if not panels:
        return False
    if len(panels) >= 2:
        return i == 0 or i == num_visits - 1
    return i == 0 and random.random() < 0.4


# ----------------------------
# Case archetypes drive a self-consistent bundle of complaints, plans,
# medications and pathology panels across multiple visits.
# ----------------------------
ARCHETYPES = [
    {
        "name": "type2_diabetes", "doctor_specialty": "chronic_disease",
        "min_age": 40, "max_age": 85, "gender": None,
        "conditions": ["Type 2 diabetes mellitus"],
        "medications": [{"name": "Metformin 500mg", "directions": "Take 1 tablet twice daily with meals."}],
        "complaints": ["Routine diabetes review.", "Increased thirst and fatigue.", "Follow-up for blood glucose control."],
        "assessments": ["Type 2 diabetes, stable on current therapy.", "Suboptimal glycaemic control, plan escalation.", "Diabetes review, no acute concerns."],
        "plan_items": ["Order HbA1c", "Dietary advice", "Monitor blood glucose at home", "Continue current medication", "Follow up in 3 months", "Refer for diabetes educator"],
        "pathology_panels": [{"panel": "HbA1c_Glucose", "bias": ["HbA1c", "Fasting Glucose"]}, {"panel": "UEC", "bias": []}],
        "visits": (3, 6), "care_plan": "GP Management Plan",
    },
    {
        "name": "hypertension", "doctor_specialty": "chronic_disease",
        "min_age": 35, "max_age": 90, "gender": None,
        "conditions": ["Essential hypertension"],
        "medications": [{"name": "Perindopril 5mg", "directions": "Take 1 tablet once daily in the morning."}],
        "complaints": ["Routine blood pressure check.", "Occasional headache.", "Follow-up for hypertension."],
        "assessments": ["Hypertension, well controlled.", "Blood pressure above target, adjust management.", "No acute findings."],
        "plan_items": ["Monitor blood pressure at home", "Lifestyle advice", "Order renal function tests", "Continue current medication", "Follow up in 6 weeks"],
        "pathology_panels": [{"panel": "UEC", "bias": []}, {"panel": "Lipids", "bias": ["Total Cholesterol", "LDL Cholesterol"]}],
        "visits": (2, 5), "care_plan": "GP Management Plan",
    },
    {
        "name": "asthma", "doctor_specialty": None,
        "min_age": 5, "max_age": 70, "gender": None,
        "conditions": ["Asthma"],
        "medications": [{"name": "Salbutamol Inhaler 100mcg", "directions": "Inhale 2 puffs as needed for shortness of breath."}],
        "complaints": ["Shortness of breath on exertion.", "Wheeze and chest tightness.", "Asthma review."],
        "assessments": ["Asthma, well controlled.", "Mild exacerbation, likely viral trigger.", "Asthma review, technique reinforced."],
        "plan_items": ["Review inhaler technique", "Order spirometry", "Continue current medication", "Follow up in 4 weeks", "Provide asthma action plan"],
        "pathology_panels": [], "visits": (2, 4), "care_plan": None,
    },
    {
        "name": "antenatal", "doctor_specialty": "womens_health",
        "min_age": 18, "max_age": 42, "gender": "Female",
        "conditions": ["Pregnancy, antenatal care"],
        "medications": [{"name": "Folic Acid 500mcg", "directions": "Take 1 tablet once daily."}],
        "complaints": ["Routine antenatal check.", "Mild nausea, otherwise well.", "Antenatal review, fetal movements normal."],
        "assessments": ["Pregnancy progressing normally.", "Antenatal review, no concerns.", "Iron studies borderline, monitor."],
        "plan_items": ["Order full blood count and iron studies", "Refer for morphology scan", "Shared care with hospital antenatal clinic", "Follow up in 4 weeks"],
        "pathology_panels": [{"panel": "FBC", "bias": ["Haemoglobin"]}, {"panel": "Iron Studies", "bias": ["Iron", "Ferritin", "Transferrin Saturation"]}],
        "visits": (3, 6), "care_plan": None,
    },
    {
        "name": "mental_health", "doctor_specialty": "mental_health",
        "min_age": 16, "max_age": 75, "gender": None,
        "conditions": ["Generalised anxiety", "Low mood"],
        "medications": [{"name": "Sertraline 50mg", "directions": "Take 1 tablet once daily."}],
        "complaints": ["Difficulty sleeping and low mood.", "Increased anxiety, affecting work.", "Follow-up mental health review."],
        "assessments": ["Mild to moderate anxiety, responding to treatment.", "Low mood, plan supportive management.", "Stable, continue current plan."],
        "plan_items": ["Prepare Mental Health Treatment Plan", "Refer to psychologist", "Continue current medication", "Follow up in 2 weeks"],
        "pathology_panels": [{"panel": "TFT", "bias": []}], "visits": (2, 5), "care_plan": "Mental Health Treatment Plan",
    },
    {
        "name": "skin_check", "doctor_specialty": None,
        "min_age": 18, "max_age": 90, "gender": None,
        "conditions": [], "medications": [],
        "complaints": ["Routine full-body skin check.", "New mole noticed on forearm.", "Follow-up on previously monitored lesion."],
        "assessments": ["No suspicious lesions identified.", "Lesion appears benign, monitor.", "Lesion referred for biopsy as precaution."],
        "plan_items": ["Photograph and monitor lesion", "Review in 6 months", "Refer to dermatologist if changes noted"],
        "pathology_panels": [], "visits": (1, 3), "care_plan": None,
    },
    {
        "name": "sports_injury", "doctor_specialty": "mens_health",
        "min_age": 15, "max_age": 55, "gender": None,
        "conditions": [], "medications": [{"name": "Ibuprofen 400mg", "directions": "Take 1 tablet every 8 hours with food as needed."}],
        "complaints": ["Knee pain after exercise.", "Shoulder strain from training.", "Follow-up on sports injury."],
        "assessments": ["Consistent with musculoskeletal strain.", "Improving, continue current management.", "Likely soft tissue inflammation."],
        "plan_items": ["Refer for physiotherapy", "Rest and ice", "Order imaging if not improving", "Follow up in 2 weeks"],
        "pathology_panels": [], "visits": (1, 3), "care_plan": None,
    },
    {
        "name": "paediatric_immunisation", "doctor_specialty": "paediatrics",
        "min_age": 0, "max_age": 16, "gender": None,
        "conditions": [], "medications": [],
        "complaints": ["Routine childhood immunisation.", "Developmental check.", "Immunisation catch-up."],
        "assessments": ["Development within normal range.", "Immunisation administered without complication.", "No concerns identified."],
        "plan_items": ["Administer scheduled vaccine", "Update immunisation register", "Provide next due date", "Routine growth check"],
        "pathology_panels": [], "visits": (2, 5), "care_plan": None,
    },
    {
        "name": "aged_care_polypharmacy", "doctor_specialty": "aged_care",
        "min_age": 70, "max_age": 95, "gender": None,
        "conditions": ["Essential hypertension", "Type 2 diabetes mellitus", "Osteoarthritis"],
        "medications": [
            {"name": "Perindopril 5mg", "directions": "Take 1 tablet once daily in the morning."},
            {"name": "Metformin 500mg", "directions": "Take 1 tablet twice daily with meals."},
            {"name": "Paracetamol 500mg", "directions": "Take 2 tablets every 6 hours as needed."},
        ],
        "complaints": ["Home Medicine Review requested.", "General wellbeing check.", "Follow-up on multiple chronic conditions."],
        "assessments": ["Stable on current medication regimen.", "Falls risk reviewed, no acute concerns.", "Polypharmacy review completed."],
        "plan_items": ["Conduct Home Medicine Review", "Falls risk assessment", "Review medication list with pharmacist", "Follow up in 3 months"],
        "pathology_panels": [{"panel": "HbA1c_Glucose", "bias": ["HbA1c"]}, {"panel": "UEC", "bias": []}, {"panel": "LFT", "bias": []}],
        "visits": (3, 6), "care_plan": "GP Management Plan",
    },
    {
        "name": "acute_general", "doctor_specialty": None,
        "min_age": 1, "max_age": 100, "gender": None,
        "conditions": [], "medications": [{"name": "Paracetamol 500mg", "directions": "Take 2 tablets every 6 hours as needed."}],
        "complaints": ["Persistent cough and sore throat.", "Fever and chills for two days.", "Abdominal pain and nausea.", "Headache and fatigue."],
        "assessments": ["Likely viral infection.", "Probable upper respiratory tract infection.", "No acute findings on examination."],
        "plan_items": ["Rest", "Increase fluid intake", "Follow up if not improving in a week", "Symptomatic relief advised"],
        "pathology_panels": [{"panel": "CRP", "bias": ["C-Reactive Protein"]}], "visits": (1, 2), "care_plan": None,
    },
]

# ----------------------------
# Secondary conditions: unrelated problems that can surface partway
# through a patient's timeline, layered onto the primary archetype so
# patients accumulate overlapping history instead of a single clean thread.
# ----------------------------
SECONDARY_CONDITIONS = [
    {
        "name": "Hypothyroidism",
        "panel": {"panel": "TFT", "bias": ["TSH"]},
        "complaint": "Ongoing fatigue and weight gain, reviewed after abnormal thyroid function.",
        "assessment": "Hypothyroidism confirmed, treatment commenced.",
        "plan_items": ["Commence thyroxine replacement", "Recheck TSH in 6 weeks", "Continue current medication", "Advise on symptoms of over-replacement"],
        "medication": {"name": "Levothyroxine 50mcg", "directions": "Take 1 tablet once daily on an empty stomach."},
    },
    {
        "name": "Iron deficiency anaemia",
        "panel": [{"panel": "FBC", "bias": ["Haemoglobin"]}, {"panel": "Iron Studies", "bias": ["Iron", "Ferritin", "Transferrin Saturation"]}],
        "complaint": "Fatigue and pallor, noted on recent bloods.",
        "assessment": "Iron deficiency anaemia, likely dietary or occult blood loss.",
        "plan_items": ["Commence iron supplementation", "Dietary advice", "Recheck FBC and iron studies in 8 weeks", "Consider further investigation if not improving"],
        "medication": {"name": "Ferro-Grad C 325mg", "directions": "Take 1 tablet once daily with food."},
    },
    {
        "name": "Gastro-oesophageal reflux disease",
        "panel": None,
        "complaint": "Heartburn and reflux after meals.",
        "assessment": "Consistent with gastro-oesophageal reflux disease.",
        "plan_items": ["Trial proton pump inhibitor", "Dietary and lifestyle advice", "Review in 4 weeks", "Continue current medication"],
        "medication": {"name": "Omeprazole 20mg", "directions": "Take 1 capsule once daily before breakfast."},
    },
    {
        "name": "Osteoarthritis",
        "panel": None,
        "complaint": "Joint stiffness and aching, worse in the mornings.",
        "assessment": "Consistent with osteoarthritis.",
        "plan_items": ["Weight management advice", "Refer for physiotherapy", "Continue current medication", "Review in 3 months"],
        "medication": {"name": "Paracetamol 500mg", "directions": "Take 2 tablets every 6 hours as needed."},
    },
    {
        "name": "Seasonal allergic rhinitis",
        "panel": None,
        "complaint": "Sneezing, itchy eyes and nasal congestion, seasonal pattern.",
        "assessment": "Consistent with seasonal allergic rhinitis.",
        "plan_items": ["Trial antihistamine", "Advise on allergen avoidance", "Review if not improving"],
        "medication": {"name": "Cetirizine 10mg", "directions": "Take 1 tablet once daily."},
    },
    {
        "name": "Dyslipidaemia",
        "panel": {"panel": "Lipids", "bias": ["Total Cholesterol", "LDL Cholesterol"]},
        "complaint": "Reviewed after elevated cholesterol noted on routine bloods.",
        "assessment": "Dyslipidaemia, above target on lipid profile.",
        "plan_items": ["Commence statin therapy", "Dietary and lifestyle advice", "Repeat lipids in 3 months", "Continue current medication"],
        "medication": {"name": "Atorvastatin 20mg", "directions": "Take 1 tablet once daily at night."},
    },
]

# ----------------------------
# Fragmentation: documents from outside the clinic's own system, with
# different formatting, identifiers, and provenance, matching the
# fragmented-records problem raised by the domain expert.
# ----------------------------
HOSPITALS = ["Sydney Central Hospital", "Harbourview Hospital", "St Augustine's Hospital", "Western District Hospital"]
IMAGING_PROVIDERS = ["Sydney Diagnostic Imaging", "CityScan Radiology", "Harbour Radiology Group"]

REFERRAL_SPECIALTY_MAP = [
    (("physio",), "Physiotherapist", "Allied Health"),
    (("psycholog",), "Clinical Psychologist", "Allied Health"),
    (("dermatolog",), "Dermatologist", "Medical Specialist"),
    (("diabetes educator",), "Credentialled Diabetes Educator", "Allied Health"),
]

IMAGING_EXAMS = {
    "sports_injury": [("X-Ray", "Knee"), ("MRI", "Shoulder"), ("Ultrasound", "Ankle")],
    "aged_care_polypharmacy": [("X-Ray", "Chest")],
    "antenatal": [("Ultrasound", "Obstetric Morphology Scan")],
}

IMAGING_FINDINGS = {
    "sports_injury": [
        ("No acute bony abnormality identified. Soft tissues unremarkable.", "No significant abnormality detected."),
        ("Mild degenerative changes noted, no acute findings.", "Correlate clinically. Follow-up as clinically indicated."),
        ("Findings consistent with soft tissue strain. No fracture identified.", "No significant abnormality detected."),
    ],
    "aged_care_polypharmacy": [
        ("Lungs clear, no focal consolidation. Heart size within normal limits.", "No significant abnormality detected."),
        ("Mild age-related changes, no acute cardiopulmonary process.", "No significant abnormality detected."),
    ],
    "antenatal": [
        ("Fetal growth parameters within normal range for gestation. Placenta normally sited.", "Normal morphology scan for gestational age."),
        ("Single live intrauterine pregnancy, growth appropriate for dates. No structural abnormality detected.", "Normal morphology scan for gestational age."),
    ],
}

HOSPITAL_PRESENTATIONS = [
    ("Fall at home", "Soft tissue injury, no fracture on X-ray.", "Analgesia given, mobilised safely, discharged."),
    ("Chest pain, query cardiac", "ECG and troponin normal, non-cardiac chest pain.", "Discharged with GP follow-up advised."),
    ("Gastroenteritis, dehydration", "Mild dehydration, responded to IV fluids.", "Discharged, advised oral rehydration."),
    ("Laceration requiring sutures", "Wound cleaned and sutured, no complications.", "Discharged, sutures to be removed by GP in 7 days."),
]

ABBREV_PATTERNS = [
    (re.compile(r"Follow up in (\d+) weeks?", re.I), r"r/v \1/52"),
    (re.compile(r"Follow up in (\d+) months?", re.I), r"r/v \1/12"),
    (re.compile(r"Review in (\d+) weeks?", re.I), r"r/v \1/52"),
    (re.compile(r"Review in (\d+) months?", re.I), r"r/v \1/12"),
    (re.compile(r"^Refer (for|to) ", re.I), "Ref "),
    (re.compile(r"^Order ", re.I), "Ix: "),
    (re.compile(r"^Continue current medication$", re.I), "Cont current meds"),
    (re.compile(r"^Monitor ", re.I), "Obs "),
    (re.compile(r"^Commence ", re.I), "Comm "),
]


def abbreviate(text):
    t = text.rstrip(".")
    for pattern, repl in ABBREV_PATTERNS:
        t = pattern.sub(repl, t)
    return t.replace(" and ", " & ")


def referral_reason_phrase(item):
    return re.sub(r"^Refer (for|to) ", "", item, flags=re.I).rstrip(".")


def ddmmyyyy(dob_str):
    y, m, d = dob_str.split("-")
    return f"{d}/{m}/{y}"


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
    ihi_number: str
    concession_type: str
    emergency_contact_name: str
    emergency_contact_phone: str
    preferred_pharmacy: str
    smoking_status: str
    alcohol_use: str
    occupation: str
    allergies: list = field(default_factory=list)
    chronic_conditions: list = field(default_factory=list)
    current_medications: list = field(default_factory=list)
    consent_status: str = "CAPTURED"
    archetype_name: str = "acute_general"
    assigned_doctor: dict = field(default_factory=dict)
    secondary_condition: str = None


class DatasetGenerator:
    def __init__(self, output_dir: str = "dataset"):
        self.output_dir = Path(output_dir)
        self.index = []

    # ----------------------------
    # Patient generation
    # ----------------------------
    def _pick_doctor(self, specialty):
        matches = [d for d in DOCTORS if d["specialty"] == specialty] if specialty else DOCTORS
        return random.choice(matches or DOCTORS)

    def _medicare_number(self):
        base = "".join(random.choices("0123456789", k=9))
        irn = random.randint(1, 9)
        return f"{base[:4]} {base[4:9]}/{irn}"

    def _ihi_number(self):
        return "8003" + "".join(random.choices("0123456789", k=12))

    def generate_patient(self, archetype: dict) -> Patient:
        gender = archetype["gender"] or random.choice(["Male", "Female"])
        dob = fake.date_of_birth(minimum_age=archetype["min_age"], maximum_age=archetype["max_age"])
        allergy = random.choice(ALLERGY_POOL)
        allergies = [allergy] if allergy else []
        conflicting = DRUG_ALLERGY_CONFLICTS.get(allergy, set())
        medications = [m for m in archetype["medications"] if m["name"] not in conflicting]

        return Patient(
            patient_id=str(uuid.uuid4()),
            first_name=fake.first_name_male() if gender == "Male" else fake.first_name_female(),
            last_name=fake.last_name(),
            dob=str(dob),
            gender=gender,
            phone=fake.phone_number(),
            email=fake.email(),
            address=fake.address().replace("\n", ", "),
            medicare_number=self._medicare_number(),
            ihi_number=self._ihi_number(),
            concession_type=random.choice(CONCESSION_TYPES),
            emergency_contact_name=fake.name(),
            emergency_contact_phone=fake.phone_number(),
            preferred_pharmacy=random.choice(PHARMACIES),
            smoking_status=random.choice(SMOKING_STATUS),
            alcohol_use=random.choice(ALCOHOL_USE),
            occupation=fake.job(),
            allergies=allergies,
            chronic_conditions=list(archetype["conditions"]),
            current_medications=medications,
            consent_status=random.choice(CONSENT_STATES),
            archetype_name=archetype["name"],
            assigned_doctor=self._pick_doctor(archetype["doctor_specialty"]),
        )

    # ----------------------------
    # Document templates
    # ----------------------------
    def consultation_note(self, patient: Patient, date, complaint, assessment, plan_items, doctor, context_note=None):
        bp = f"{random.randint(105, 150)}/{random.randint(65, 95)}"
        weight = round(random.uniform(50, 110), 1)
        style = doctor["note_style"]
        conditions = ", ".join(patient.chronic_conditions) or ("nil significant" if style == "terse" else "None recorded")
        allergies = ", ".join(patient.allergies) if patient.allergies else ("NKDA" if style == "terse" else "No known drug allergies")

        if style == "terse":
            plan_line = "; ".join(abbreviate(p) for p in plan_items)
            note = f"{date.strftime('%d/%m/%y')} - {doctor['name'].split()[-1]}\n"
            note += f"c/o {complaint.rstrip('.').lower()}\n"
            if context_note:
                note += f"{context_note}\n"
            note += f"Hx: {conditions}. Allergies: {allergies}\n"
            note += f"O/E: BP {bp}, Wt {weight}kg\n"
            note += f"Imp: {assessment.rstrip('.').lower()}\n"
            note += f"Plan: {plan_line}\n"
            return note

        if style == "soap":
            plan_line = "; ".join(plan_items)
            note = f"Consultation - {date.strftime('%d/%m/%Y')} - {doctor['name']}\n\n"
            note += f"S: {complaint}" + (f" {context_note}" if context_note else "") + "\n"
            note += f"O: BP {bp} mmHg, Wt {weight}kg. Known conditions: {conditions}. Allergies: {allergies}\n"
            note += f"A: {assessment}\n"
            note += f"P: {plan_line}\n"
            return note

        plan = "\n".join(f"- {item}" for item in plan_items)
        note_field = f"\nNote: {context_note}\n" if context_note else ""
        return f"""Consultation Note

Patient: {patient.first_name} {patient.last_name}
DOB: {patient.dob}
Date: {date.strftime('%d/%m/%Y')}
Seen by: {doctor['name']}

Known conditions: {conditions}
Allergies: {allergies}
{note_field}
Vitals: BP {bp} mmHg, Weight {weight} kg

Chief Complaint:
{complaint}

Assessment:
{assessment}

Plan:
{plan}
"""

    def prescription(self, patient: Patient, date, doctor):
        # Quantity/repeats are real AU-script fields that legitimately vary visit to
        # visit even when directions don't; a review note occasionally appears too.
        # Not a dose-titration model -- that's tracked per medication in
        # patient.current_medications and only changes on a secondary-condition onset.
        review_notes = ["", "", "Continuing current dose, well tolerated.", "Reviewed today, no change."]
        entries = []
        for m in patient.current_medications:
            qty = random.choice([30, 60, 90])
            repeats = random.randint(0, 5)
            note = random.choice(review_notes)
            entry = f"{m['name']}\n{m['directions']}\nQuantity: {qty}  Repeats: {repeats}"
            if note:
                entry += f"\n{note}"
            entries.append(entry)
        meds = "\n\n".join(entries)
        return f"""Prescription

Patient: {patient.first_name} {patient.last_name}
DOB: {patient.dob}
Date: {date.strftime('%d/%m/%Y')}
Prescribed by: {doctor['name']}

{meds}
"""

    def pathology_report(self, patient: Patient, date, panel_name, rows, flagged, doctor):
        table = format_panel_table(rows)
        interpretation = (
            "One or more results outside reference range, recommend clinical correlation."
            if flagged else "Results within expected reference ranges."
        )
        return f"""Pathology Report

Patient: {patient.first_name} {patient.last_name}
DOB: {patient.dob}
Date collected: {date.strftime('%d/%m/%Y')}
Requested by: {doctor['name']}

{panel_name}

{table}

Interpretation: {interpretation}
"""

    def referral_letter(self, patient: Patient, date, reason, doctor):
        return f"""Referral Letter

Date: {date.strftime('%d/%m/%Y')}
Referring doctor: {doctor['name']}
Patient: {patient.first_name} {patient.last_name}
DOB: {patient.dob}
Medicare: {patient.medicare_number}

Reason for referral:
{reason}

Relevant history: {", ".join(patient.chronic_conditions) or "None recorded"}
Allergies: {", ".join(patient.allergies) or "No known drug allergies"}
"""

    def care_plan(self, patient: Patient, date, plan_type, doctor):
        conditions = ", ".join(patient.chronic_conditions) or "None recorded"
        return f"""{plan_type}

Patient: {patient.first_name} {patient.last_name}
DOB: {patient.dob}
Date prepared: {date.strftime('%d/%m/%Y')}
Prepared by: {doctor['name']}

Conditions addressed: {conditions}
Review due: 12 months from date prepared, or earlier if clinically indicated.
"""

    def registration_form(self, patient: Patient):
        return f"""Patient Registration Form

Name: {patient.first_name} {patient.last_name}
DOB: {patient.dob}
Gender: {patient.gender}
Phone: {patient.phone}
Email: {patient.email}
Address: {patient.address}

Medicare number: {patient.medicare_number}
IHI: {patient.ihi_number}
Concession card: {patient.concession_type or "None"}

Emergency contact: {patient.emergency_contact_name}, {patient.emergency_contact_phone}
Preferred pharmacy: {patient.preferred_pharmacy}

Smoking status: {patient.smoking_status}
Alcohol use: {patient.alcohol_use}
Occupation: {patient.occupation}
Allergies: {", ".join(patient.allergies) or "No known drug allergies"}
Assigned doctor: {patient.assigned_doctor['name']}
"""

    def consent_record(self, patient: Patient, date):
        if patient.consent_status == "CAPTURED":
            body = (
                "Patient confirmed they read the consent form, had the opportunity to ask "
                "questions, and agreed to share records with other treating providers. "
                "Research participation: declined."
            )
        elif patient.consent_status == "PENDING":
            body = (
                "Consent form partially completed. Information-sharing section not yet signed."
            )
        else:
            body = "Patient withdrew consent to share records with other providers."

        return f"""Consent Record

Patient: {patient.first_name} {patient.last_name}
DOB: {patient.dob}
Date: {date.strftime('%d/%m/%Y')}
Status: {patient.consent_status}

{body}
"""

    def appointment_history(self, patient: Patient, visit_lines):
        lines = "\n".join(visit_lines)
        return f"""Appointment History

Patient: {patient.first_name} {patient.last_name}

{lines}
"""

    def specialist_letter(self, patient: Patient, date, reason_phrase, gp_doctor):
        keywords_title = next(
            ((title, category) for keywords, title, category in REFERRAL_SPECIALTY_MAP
             if any(k in reason_phrase.lower() for k in keywords)),
            ("Specialist Physician", "Medical Specialist"),
        )
        title, category = keywords_title
        specialist_name = fake.name()
        header_name = f"Dr {specialist_name}" if category == "Medical Specialist" else specialist_name
        gp_last = gp_doctor["name"].split()[-1]
        closing = random.choice([
            "I will review again in 6 weeks.",
            "I am happy to hand ongoing management back to your care.",
            "Please continue current management and re-refer if symptoms recur.",
        ])

        return f"""{header_name}
{title}
Suite {random.randint(1, 20)}, {fake.street_address()}, Sydney NSW 2000

Dear Dr {gp_last},

Re: {patient.last_name}, {patient.first_name} (DOB {ddmmyyyy(patient.dob)})

Thank you for referring this patient. I reviewed them on {date.strftime('%d/%m/%Y')} regarding {reason_phrase}.

On assessment, findings were consistent with the referral concern. Management has been discussed with the patient and a plan put in place.

{closing}

Kind regards,
{header_name}
{title}
"""

    def external_imaging_report(self, patient: Patient, date, modality, body_part, gp_doctor, archetype_name):
        provider = random.choice(IMAGING_PROVIDERS)
        accession = f"RAD-{random.randint(100000, 999999)}"
        lastname_first = f"{patient.last_name.upper()}, {patient.first_name}"
        findings, impression = random.choice(IMAGING_FINDINGS[archetype_name])

        return f"""{provider}
Sydney NSW | Ph: (02) 8{random.randint(100, 999)} {random.randint(1000, 9999)}

RADIOLOGY REPORT

Accession No: {accession}
Patient: {lastname_first}
DOB: {ddmmyyyy(patient.dob)}
Referring Doctor: {gp_doctor['name']}, GreenCare Family Medical Clinic

Exam: {modality} - {body_part}
Date of exam: {date.strftime('%d/%m/%Y')}

FINDINGS:
{findings}

IMPRESSION:
{impression}

Report received via secure fax and filed against patient record.
"""

    def hospital_discharge_summary(self, patient: Patient, date, discharge_date):
        presentation, findings, management = random.choice(HOSPITAL_PRESENTATIONS)
        hospital = random.choice(HOSPITALS)
        ur_number = f"UR{random.randint(1000000, 9999999)}"
        lastname_first = f"{patient.last_name.upper()}, {patient.first_name}"

        return f"""{hospital.upper()}
EMERGENCY DEPARTMENT DISCHARGE SUMMARY

UR Number: {ur_number}
Patient: {lastname_first}
DOB: {ddmmyyyy(patient.dob)}
Presented: {date.strftime('%d/%m/%Y')}
Discharged: {discharge_date.strftime('%d/%m/%Y')}

Presenting complaint: {presentation}

Findings: {findings}

Management: {management}

Discharge plan: Follow up with regular GP within one week. Copy forwarded to GreenCare Family Medical Clinic.
"""

    # ----------------------------
    # File handling
    # ----------------------------
    def create_patient_directories(self, patient: Patient):
        patient_folder = self.output_dir / f"{patient.first_name}_{patient.last_name}_{patient.patient_id}"
        clinical_folder = patient_folder / "Clinical_Docs"
        admin_folder = patient_folder / "Admin_Docs"
        clinical_folder.mkdir(parents=True, exist_ok=True)
        admin_folder.mkdir(parents=True, exist_ok=True)
        return patient_folder, clinical_folder, admin_folder

    def save_document(self, folder: Path, filename: str, content: str, manifest: list, doc_type: str, date=None, source="internal"):
        (folder / filename).write_text(content, encoding="utf-8")
        manifest.append({
            "filename": filename,
            "doc_type": doc_type,
            "classification": DOC_CLASSIFICATION[doc_type],
            "source": source,
            "date": date.isoformat() if date else None,
        })

    # ----------------------------
    # Per-patient longitudinal record
    # ----------------------------
    def generate_patient_record(self, archetype: dict):
        patient = self.generate_patient(archetype)
        patient_folder, clinical, admin = self.create_patient_directories(patient)
        doctor = patient.assigned_doctor
        manifest = []

        num_visits = random.randint(*archetype["visits"])
        visit_dates = sorted(fake.date_between(start_date="-2y", end_date="today") for _ in range(num_visits))

        eligible_secondary = [c for c in SECONDARY_CONDITIONS if c["name"] not in patient.chronic_conditions]
        has_secondary = num_visits >= 2 and eligible_secondary and random.random() < 0.4
        secondary = random.choice(eligible_secondary) if has_secondary else None
        onset_index = random.randint(1, num_visits - 1) if has_secondary else None
        if secondary:
            patient.secondary_condition = secondary["name"]

        has_hospital_event = random.random() < 0.12
        hospital_date = None
        aware_visit_index = None
        if has_hospital_event:
            hospital_date = fake.date_between(start_date=visit_dates[0], end_date="today")
            discharge_date = min(hospital_date + timedelta(days=random.randint(0, 2)), date_cls.today())
            self.save_document(
                clinical, f"hospital_discharge_{hospital_date.isoformat()}.txt",
                self.hospital_discharge_summary(patient, hospital_date, discharge_date),
                manifest, "hospital_discharge_summary", hospital_date, source="external",
            )
            later = [i for i, d in enumerate(visit_dates) if d > hospital_date]
            aware_visit_index = later[0] if later else None

        visit_lines = []
        for i, date in enumerate(visit_dates):
            is_onset = has_secondary and i == onset_index
            is_secondary_visit = is_onset or (secondary and i > onset_index and random.random() < 0.5)

            if is_secondary_visit:
                complaint = secondary["complaint"]
                assessment = secondary["assessment"]
                plan_items = random.sample(secondary["plan_items"], k=min(len(secondary["plan_items"]), random.randint(2, 3)))
            else:
                complaint = random.choice(archetype["complaints"])
                assessment = random.choice(archetype["assessments"])
                plan_items = random.sample(archetype["plan_items"], k=min(len(archetype["plan_items"]), random.randint(2, 4)))

            if is_onset:
                patient.chronic_conditions.append(secondary["name"])
                med = secondary["medication"]
                if med:
                    conflicting = DRUG_ALLERGY_CONFLICTS.get(patient.allergies[0] if patient.allergies else None, set())
                    if med["name"] not in conflicting:
                        patient.current_medications.append(med)

            context_note = None
            if aware_visit_index is not None and i == aware_visit_index:
                context_note = f"Aware of recent hospital presentation on {hospital_date.strftime('%d/%m/%Y')}, no new concerns raised today."

            referral_triggered = any(item.lower().startswith("refer") for item in plan_items)

            self.save_document(
                clinical, f"consultation_{date.isoformat()}.txt",
                self.consultation_note(patient, date, complaint, assessment, plan_items, doctor, context_note),
                manifest, "consultation_note", date,
            )

            if patient.current_medications:
                self.save_document(
                    clinical, f"prescription_{date.isoformat()}.txt",
                    self.prescription(patient, date, doctor),
                    manifest, "prescription", date,
                )

            panels_run = []
            if should_run_panels(archetype, i, num_visits):
                panels_run.extend(archetype["pathology_panels"] if i == 0 else [archetype["pathology_panels"][0]])
            if is_onset and secondary["panel"]:
                sp = secondary["panel"]
                panels_run.extend(sp if isinstance(sp, list) else [sp])
            if not panels_run and random.random() < 0.12:
                panels_run.append({"panel": random.choice(["FBC", "UEC"]), "bias": []})

            appointment_type = "General Consultation"
            if archetype["name"] == "paediatric_immunisation":
                appointment_type = "Vaccination"
            elif referral_triggered:
                appointment_type = "Specialist Referral"
            elif panels_run:
                appointment_type = "Blood Test"
            elif i > 0:
                appointment_type = "Follow-up Review"

            for entry in panels_run:
                rows, flagged = render_panel(patient, entry["panel"], entry.get("bias"))
                slug = entry["panel"].replace(" ", "_").lower()
                self.save_document(
                    clinical, f"pathology_{date.isoformat()}_{slug}.txt",
                    self.pathology_report(patient, date, entry["panel"], rows, flagged, doctor),
                    manifest, "pathology_report", date,
                )

            if referral_triggered:
                reason = next(item for item in plan_items if item.lower().startswith("refer"))
                self.save_document(
                    clinical, f"referral_{date.isoformat()}.txt",
                    self.referral_letter(patient, date, reason, doctor),
                    manifest, "referral_letter", date,
                )
                reason_phrase = referral_reason_phrase(reason)
                reply_date = date + timedelta(weeks=random.randint(3, 8))
                if reply_date <= date_cls.today() and random.random() < 0.55:
                    self.save_document(
                        clinical, f"specialist_letter_{reply_date.isoformat()}.txt",
                        self.specialist_letter(patient, reply_date, reason_phrase, doctor),
                        manifest, "specialist_letter", reply_date, source="external",
                    )

            imaging_options = IMAGING_EXAMS.get(archetype["name"])
            wants_imaging = imaging_options and any("imaging" in p.lower() or "scan" in p.lower() for p in plan_items)
            if wants_imaging:
                imaging_date = date + timedelta(weeks=random.randint(1, 3))
                if imaging_date <= date_cls.today():
                    modality, body_part = random.choice(imaging_options)
                    self.save_document(
                        clinical, f"imaging_{imaging_date.isoformat()}.txt",
                        self.external_imaging_report(patient, imaging_date, modality, body_part, doctor, archetype["name"]),
                        manifest, "external_imaging_report", imaging_date, source="external",
                    )

            visit_lines.append(f"{date.strftime('%d/%m/%Y')} - {appointment_type} - {doctor['name']}")

        if archetype["care_plan"]:
            self.save_document(
                clinical, f"care_plan_{visit_dates[0].isoformat()}.txt",
                self.care_plan(patient, visit_dates[0], archetype["care_plan"], doctor),
                manifest, "care_plan", visit_dates[0],
            )

        self.save_document(admin, "registration_form.txt", self.registration_form(patient), manifest, "registration_form")
        self.save_document(admin, "appointment_history.txt", self.appointment_history(patient, visit_lines), manifest, "appointment_history")
        self.save_document(
            admin, "consent_record.txt",
            self.consent_record(patient, visit_dates[0]),
            manifest, "consent_record", visit_dates[0],
        )

        (patient_folder / "manifest.json").write_text(
            json.dumps({
                "patient_id": patient.patient_id,
                "name": f"{patient.first_name} {patient.last_name}",
                "dob": patient.dob,
                "gender": patient.gender,
                "archetype": patient.archetype_name,
                "chronic_conditions": patient.chronic_conditions,
                "secondary_condition": patient.secondary_condition,
                "hospital_event_date": hospital_date.isoformat() if hospital_date else None,
                "allergies": patient.allergies,
                "assigned_doctor": doctor["name"],
                "assigned_doctor_id": doctor["id"],
                "note_style": doctor["note_style"],
                "consent_status": patient.consent_status,
                "documents": manifest,
            }, indent=2),
            encoding="utf-8",
        )

        self.index.append({
            "patient_id": patient.patient_id,
            "name": f"{patient.first_name} {patient.last_name}",
            "archetype": patient.archetype_name,
            "secondary_condition": patient.secondary_condition,
            "hospital_event": hospital_date is not None,
            "assigned_doctor_id": doctor["id"],
            "consent_status": patient.consent_status,
        })

    def generate_dataset(self, num_patients: int):
        for _ in range(num_patients):
            archetype = random.choice(ARCHETYPES)
            self.generate_patient_record(archetype)

        (self.output_dir / "index.json").write_text(json.dumps(self.index, indent=2), encoding="utf-8")
        print(f"Dataset generated in: {self.output_dir} ({num_patients} patients)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a synthetic longitudinal patient dataset for VitalAI RAG testing.")
    parser.add_argument("--patients", type=int, default=20)
    parser.add_argument("--output-dir", type=str, default="dataset")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
        Faker.seed(args.seed)

    DatasetGenerator(output_dir=args.output_dir).generate_dataset(args.patients)
