# VitalAI API reference

All 125 routes, with the access check on each, taken from the app's own route registry (`get_rbac_registry(app)`) with the Twilio routes enabled. This is the full version of Appendix D of the A5 technical report. Request and response shapes are in the interactive OpenAPI documentation at `/docs` on a running server.

| Method | Path | Access check | Router file |
|---|---|---|---|
| GET | `/api/v1/appointments` | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | `appointments.py` |
| POST | `/api/v1/appointments` | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | `appointments.py` |
| GET | `/api/v1/appointments/availability` | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | `appointments.py` |
| GET | `/api/v1/appointments/calendar` | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | `appointments.py` |
| GET | `/api/v1/appointments/calendar/markers` | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | `appointments.py` |
| GET | `/api/v1/appointments/day` | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | `appointments.py` |
| POST | `/api/v1/appointments/suggest` | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | `appointments.py` |
| GET | `/api/v1/appointments/{appointment_id}` | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | `appointments.py` |
| PATCH | `/api/v1/appointments/{appointment_id}` | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | `appointments.py` |
| POST | `/api/v1/appointments/{appointment_id}/cancel` | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | `appointments.py` |
| POST | `/api/v1/appointments/{appointment_id}/complete` | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | `appointments.py` |
| POST | `/api/v1/appointments/{appointment_id}/reschedule` | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | `appointments.py` |
| GET | `/api/v1/approvals` | MANAGE_CASES | `approvals.py` |
| POST | `/api/v1/approvals/{approval_id}/approve` | APPROVE_ACTION | `approvals.py` |
| POST | `/api/v1/approvals/{approval_id}/reject` | APPROVE_ACTION | `approvals.py` |
| GET | `/api/v1/assignments` | ASSIGN_PATIENTS | `assignments.py` |
| POST | `/api/v1/assignments` | ASSIGN_PATIENTS | `assignments.py` |
| DELETE | `/api/v1/assignments/{doctor_id}/{patient_id}` | ASSIGN_PATIENTS | `assignments.py` |
| GET | `/api/v1/audit` | READ_AUDIT | `audit.py` |
| GET | `/api/v1/audit/by-case/{case_id}` | READ_AUDIT | `audit.py` |
| GET | `/api/v1/audit/incidents` | READ_AUDIT | `audit.py` |
| GET | `/api/v1/audit/verify` | READ_AUDIT | `audit.py` |
| GET | `/api/v1/audit/{event_id}` | READ_AUDIT | `audit.py` |
| POST | `/api/v1/auth/login` | Public, rate limited | `auth.py` |
| GET | `/api/v1/auth/me` | Any signed-in user | `auth.py` |
| POST | `/api/v1/auth/me/password` | Any signed-in user | `auth.py` |
| POST | `/api/v1/auth/password-reset/confirm` | Public, rate limited | `auth.py` |
| POST | `/api/v1/auth/password-reset/request` | Public, rate limited | `auth.py` |
| POST | `/api/v1/auth/register` | MANAGE_USERS | `auth.py` |
| GET | `/api/v1/auth/users` | MANAGE_USERS | `auth.py` |
| POST | `/api/v1/auth/users/{user_id}/active` | MANAGE_USERS | `auth.py` |
| POST | `/api/v1/auth/users/{user_id}/department` | MANAGE_USERS | `auth.py` |
| POST | `/api/v1/auth/users/{user_id}/elevate` | MANAGE_USERS | `auth.py` |
| GET | `/api/v1/auth/users/{user_id}/grants` | MANAGE_USERS | `auth.py` |
| POST | `/api/v1/auth/users/{user_id}/grants` | MANAGE_USERS | `auth.py` |
| DELETE | `/api/v1/auth/users/{user_id}/grants/{permission}` | MANAGE_USERS | `auth.py` |
| GET | `/api/v1/calls` | VIEW_QUEUE | `calls.py` |
| POST | `/api/v1/calls` | VIEW_QUEUE | `calls.py` |
| POST | `/api/v1/calls/transcribe` | VIEW_QUEUE | `calls.py` |
| GET | `/api/v1/calls/{call_id}` | VIEW_QUEUE | `calls.py` |
| GET | `/api/v1/calls/{call_id}/audio` | PLAY_VOICEMAIL | `calls.py` |
| POST | `/api/v1/calls/{call_id}/escalate` | MANAGE_CASES | `calls.py` |
| POST | `/api/v1/calls/{call_id}/override-routing` | MANAGE_CASES | `calls.py` |
| POST | `/api/v1/calls/{call_id}/route` | MANAGE_CASES | `calls.py` |
| GET | `/api/v1/cases` | VIEW_RECORDS_GENERAL | `episodes.py` |
| POST | `/api/v1/cases` | REGISTER_PATIENT or VIEW_CLINICAL | `episodes.py` |
| POST | `/api/v1/cases/move` | REGISTER_PATIENT or VIEW_CLINICAL | `episodes.py` |
| GET | `/api/v1/cases/{episode_id}` | VIEW_RECORDS_GENERAL | `episodes.py` |
| PATCH | `/api/v1/cases/{episode_id}` | REGISTER_PATIENT or VIEW_CLINICAL | `episodes.py` |
| POST | `/api/v1/cases/{episode_id}/close` | REGISTER_PATIENT or VIEW_CLINICAL | `episodes.py` |
| POST | `/api/v1/cases/{episode_id}/contact` | REGISTER_PATIENT or VIEW_CLINICAL | `episodes.py` |
| POST | `/api/v1/cases/{episode_id}/reopen` | REGISTER_PATIENT or VIEW_CLINICAL | `episodes.py` |
| GET | `/api/v1/clinical-documents` | UPLOAD_CLINICAL or VIEW_CLINICAL | `clinical_documents.py` |
| POST | `/api/v1/clinical-documents` | UPLOAD_CLINICAL | `clinical_documents.py` |
| GET | `/api/v1/clinical-documents/{document_id}/file` | VIEW_CLINICAL | `clinical_documents.py` |
| POST | `/api/v1/clinical-documents/{document_id}/ingest` | UPLOAD_CLINICAL | `clinical_documents.py` |
| GET | `/api/v1/consent` | VIEW_RECORDS_GENERAL | `consent.py` |
| POST | `/api/v1/consent` | CAPTURE_CONSENT | `consent.py` |
| GET | `/api/v1/consent/by-case/{case_id}` | VIEW_RECORDS_GENERAL | `consent.py` |
| GET | `/api/v1/consent/queue` | CAPTURE_CONSENT | `consent.py` |
| POST | `/api/v1/consent/{consent_id}/capture` | CAPTURE_CONSENT | `consent.py` |
| POST | `/api/v1/consent/{consent_id}/resolve-review` | CAPTURE_CONSENT | `consent.py` |
| POST | `/api/v1/consent/{consent_id}/verify` | CAPTURE_CONSENT | `consent.py` |
| POST | `/api/v1/consent/{consent_id}/withdraw` | CAPTURE_CONSENT | `consent.py` |
| GET | `/api/v1/doctors` | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | `doctors.py` |
| POST | `/api/v1/email/ingest` | VIEW_QUEUE | `email.py` |
| GET | `/api/v1/health/detailed` | READ_AUDIT | `health.py` |
| GET | `/api/v1/human-review` | VIEW_CLINICAL or VIEW_QUEUE | `human_review.py` |
| POST | `/api/v1/human-review` | VIEW_CLINICAL or VIEW_QUEUE | `human_review.py` |
| GET | `/api/v1/human-review/stats/daily` | VIEW_CLINICAL or VIEW_QUEUE | `human_review.py` |
| POST | `/api/v1/human-review/{task_id}/case-close` | VIEW_CLINICAL or VIEW_QUEUE | `human_review.py` |
| POST | `/api/v1/human-review/{task_id}/choose-case` | VIEW_CLINICAL or VIEW_QUEUE | `human_review.py` |
| POST | `/api/v1/human-review/{task_id}/claim` | VIEW_CLINICAL or VIEW_QUEUE | `human_review.py` |
| POST | `/api/v1/human-review/{task_id}/complete` | VIEW_CLINICAL or VIEW_QUEUE | `human_review.py` |
| POST | `/api/v1/human-review/{task_id}/escalate` | VIEW_CLINICAL or VIEW_QUEUE | `human_review.py` |
| POST | `/api/v1/human-review/{task_id}/link-patient` | VIEW_CLINICAL or VIEW_QUEUE | `human_review.py` |
| POST | `/api/v1/human-review/{task_id}/reassign` | VIEW_CLINICAL or VIEW_QUEUE | `human_review.py` |
| POST | `/api/v1/human-review/{task_id}/reject` | VIEW_CLINICAL or VIEW_QUEUE | `human_review.py` |
| POST | `/api/v1/human-review/{task_id}/reroute` | VIEW_CLINICAL or VIEW_QUEUE | `human_review.py` |
| GET | `/api/v1/inbox` | VIEW_CLINICAL or VIEW_QUEUE | `inbox.py` |
| GET | `/api/v1/inbox/{task_id}` | VIEW_CLINICAL or VIEW_QUEUE | `inbox.py` |
| POST | `/api/v1/inbox/{task_id}/reply` | VIEW_CLINICAL or VIEW_QUEUE | `inbox.py` |
| GET | `/api/v1/intake` | VIEW_QUEUE | `intake.py` |
| POST | `/api/v1/intake` | VIEW_QUEUE | `intake.py` |
| GET | `/api/v1/intake/{case_id}` | VIEW_QUEUE | `intake.py` |
| PATCH | `/api/v1/intake/{case_id}/status` | MANAGE_CASES | `intake.py` |
| GET | `/api/v1/integrations/outlook` | CONFIGURE_GOVERNANCE | `integrations.py` |
| GET | `/api/v1/integrations/outlook/callback` | Public, Microsoft OAuth redirect (single-use state) | `integrations.py` |
| POST | `/api/v1/integrations/outlook/connect` | CONFIGURE_GOVERNANCE | `integrations.py` |
| POST | `/api/v1/llm/ping` | Role admin or operator | `llm.py` |
| GET | `/api/v1/llm/status` | Role admin or operator | `llm.py` |
| GET | `/api/v1/patients` | VIEW_RECORDS_GENERAL | `patients.py` |
| POST | `/api/v1/patients` | REGISTER_PATIENT | `patients.py` |
| GET | `/api/v1/patients/{patient_id}` | VIEW_RECORDS_GENERAL | `patients.py` |
| PATCH | `/api/v1/patients/{patient_id}` | REGISTER_PATIENT | `patients.py` |
| PUT | `/api/v1/patients/{patient_id}/doctor` | ASSIGN_PATIENTS | `patients.py` |
| POST | `/api/v1/patients/{patient_id}/promote` | REGISTER_PATIENT | `patients.py` |
| GET | `/api/v1/public/registration/{token}` | Public, rate limited, token | `public_registration.py` |
| POST | `/api/v1/public/registration/{token}` | Public, rate limited, token | `public_registration.py` |
| GET | `/api/v1/rag/documents` | VIEW_CLINICAL | `rag.py` |
| POST | `/api/v1/rag/query` | VIEW_CLINICAL | `rag.py` |
| GET | `/` | Public | `app/main.py` |
| GET | `/health` | Public | `health.py` |
| POST | `/api/v1/routing` | MANAGE_CASES | `routing.py` |
| GET | `/api/v1/routing/by-case/{case_id}` | VIEW_QUEUE | `routing.py` |
| GET | `/api/v1/settings` | CONFIGURE_GOVERNANCE | `settings.py` |
| PATCH | `/api/v1/settings` | CONFIGURE_GOVERNANCE | `settings.py` |
| GET | `/api/v1/tasks` | VIEW_QUEUE | `tasks.py` |
| POST | `/api/v1/tasks` | MANAGE_CASES | `tasks.py` |
| DELETE | `/api/v1/tasks/{task_id}` | DELETE_MESSAGES | `tasks.py` |
| GET | `/api/v1/tasks/{task_id}` | VIEW_QUEUE | `tasks.py` |
| PATCH | `/api/v1/tasks/{task_id}` | MANAGE_CASES | `tasks.py` |
| POST | `/api/v1/tasks/{task_id}/archive` | VIEW_CLINICAL or VIEW_QUEUE | `tasks.py` |
| GET | `/api/v1/tasks/{task_id}/comments` | VIEW_QUEUE | `tasks.py` |
| POST | `/api/v1/tasks/{task_id}/comments` | VIEW_QUEUE | `tasks.py` |
| POST | `/api/v1/tasks/{task_id}/escalate` | VIEW_CLINICAL or VIEW_QUEUE | `tasks.py` |
| POST | `/api/v1/tasks/{task_id}/override` | MANAGE_CASES | `tasks.py` |
| POST | `/api/v1/tasks/{task_id}/read` | VIEW_CLINICAL or VIEW_QUEUE | `tasks.py` |
| POST | `/api/v1/triage` | MANAGE_CASES | `triage.py` |
| POST | `/api/v1/voice/done` | Public, Twilio signature checked | `voice.py` |
| POST | `/api/v1/voice/gather/{step}` | Public, Twilio signature checked | `voice.py` |
| POST | `/api/v1/voice/incoming` | Public, Twilio signature checked | `voice.py` |
| POST | `/api/v1/voice/recording` | Public, Twilio signature checked | `voice.py` |
| POST | `/api/v1/voice/status` | Public, Twilio signature checked | `voice.py` |
| POST | `/api/v1/voicemails/simulate` | MANAGE_CASES | `voicemails.py` |
