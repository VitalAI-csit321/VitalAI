<!-- doc_type: staff_directory | access_scope: sensitive -->

# Staff Directory

Internal document. Demo login accounts and RBAC mapping. Never surfaced to patients. Demo passwords are non-production and exist only for the presentation.

## Directory

| Staff name | Position | System role | Username | Per-user grants | Notes |
| --- | --- | --- | --- | --- | --- |
| Sarah Khan | Front Desk Receptionist | FRONT_DESK | frontdesk01 | none | Bookings, basic patient info |
| James Li | Front Desk Receptionist | FRONT_DESK | frontdesk02 | none | Appointment coordination |
| Emily Carter | Back Office Staff | OPERATOR | operator01 | none | Documents, admin workflows |
| Daniel Singh | Back Office Staff | OPERATOR | operator02 | VIEW_CLINICAL | Processes referrals, granted clinical read for referral triage (example of a per-user grant) |
| Michael Brown | Operational Manager | ADMIN | admin01 | none | Full operational control, billing, consent |
| Olivia Chen | System Administrator | ADMIN | admin02 | none | System configuration |
| Dr Aisha Rahman | General Practitioner | DOCTOR | doctor01 | (clinical by role) | Special interest: women's health, antenatal care |
| Dr David Nguyen | General Practitioner | DOCTOR | doctor02 | (clinical by role) | Special interest: chronic disease, diabetes |
| Dr Priya Menon | General Practitioner | DOCTOR | doctor03 | (clinical by role) | Special interest: mental health, skin checks |
| Dr Marcus O'Connell | General Practitioner | DOCTOR | doctor04 | (clinical by role) | Special interest: men's health, sports medicine |
| Dr Hannah Fitzgerald | General Practitioner | DOCTOR | doctor05 | (clinical by role) | Special interest: paediatrics, child health |
| Dr Samuel Osei | General Practitioner | DOCTOR | doctor06 | (clinical by role) | Special interest: aged care, home medicine reviews. Waitlist only for new patients |

All six doctors are read-only inside VitalAI, manage their own calendar, and are scoped to their own assigned patients through `doctor_patient_assignments`. Full weekly schedules and special interest detail live in Clinic Identity, since that document is patient-facing; this directory holds the RBAC and login mapping only.

The display label "Back Office" or "Operations" corresponds to the system role `OPERATOR`. The token stored and matched by the system is always `OPERATOR`, never `OPS`.

## RBAC Role Definitions

| System role | Description |
| --- | --- |
| FRONT_DESK | Patient-facing administrative tasks: booking, reschedule, cancellation, general enquiry, registration intake |
| OPERATOR | Internal workflows: referral document handling, document intake, operational processing |
| ADMIN | Full operational access: billing, refunds, consent decisions, complaints, system configuration. No clinical decision-making |
| DOCTOR | Clinical read within VitalAI, own calendar management, own assigned patients only |

## Hybrid Access Model

Access is not role alone. It is three layers combined:

1. **RBAC core.** The role sets the baseline of what a user can reach.
2. **Per-user grants.** Individual permissions can be granted on top of a role. `VIEW_CLINICAL` is the grantable clinical-read permission. A granted non-doctor (see operator02 above) can read clinical data across patients. A doctor's clinical read comes from the role and is scoped to assigned patients.
3. **Row-level scoping.** Doctors see only patients assigned to them, resolved through the `doctor_patient_assignments` table. A doctor cannot see another doctor's patients or calendar.

## Doctor Constraints

- Read-only inside VitalAI. Doctors do not perform administrative writes in the platform.
- Manage their own calendar only.
- Cannot view another doctor's calendar or patients.
- Clinical judgement, prescriptions, and referral approvals happen through the doctor, not the system.

## Usage in System

This directory supports:

- RBAC enforcement (which role reaches which data).
- Security testing (SEC-RBAC validation, and Ariana's threat model and adversarial corpus).
- Demo login accounts for the presentation.
- Access control validation across workflows, including the per-user grant and row-level scoping paths, not just role checks.
