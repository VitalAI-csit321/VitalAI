# VitalAI data dictionary

The database has 22 tables with 283 columns, taken from the SQLAlchemy models. Each description comes from the comment on that column in the model, or from the code that uses it. This is the full version of Appendix C of the A5 technical report. Constraint shorthand: PK primary key, FK foreign key, NOT NULL, UNIQUE, INDEX, GENERATED (computed by Postgres), server default.

## 1. Enum types

| Enum | Values |
|---|---|
| `appointment_status` | pending, confirmed, cancelled, completed |
| `appointment_type` | new_patient, follow_up, procedure, other |
| `approval_status` | pending, approved, rejected |
| `call_kind` | logged, voicemail |
| `call_status` | received, processed, escalated, in_progress, recording, processing, abandoned |
| `clinical_doc_type` | consultation, consultation_note, pathology_report, prescription, registration_form, appointment_history, referral_letter, care_plan, specialist_letter, hospital_discharge_summary, external_imaging_report, consent_record |
| `consent_status` | pending, captured, withdrawn, not_required |
| `episode_status` | open, closed |
| `gender` | male, female, non_binary |
| `intake_status` | intake_received, intake_incomplete, consent_pending, consent_captured, context_ready, context_insufficient, triage_routine, triage_time_sensitive, triage_immediate, routed, escalated |
| `medication_status` | active, discontinued, expired |
| `patient_status` | active, pending, inactive |
| `routing_action` | admin_workflow, human_review, direct_escalation |
| `task_category` | appointment_request, new_patient_onboarding, prescription_renewal, results_enquiry, referral_request, medical_records_request, billing_insurance_enquiry, complaint_escalation, general_administrative, urgent_emergency |
| `task_priority` | low, medium, high, urgent |
| `task_source` | email, call |
| `task_status` | pending, in_progress, completed, cancelled, escalated |
| `task_type` | triage_review, consent_review, escalation_review, routing_review, draft_approval, intent_review, identity_review, agent_failure, agent_handover, complaint_review, case_choice, case_close, prescription_request |
| `triage_category` | routine, time_sensitive, immediate, low_confidence_manual_review |
| `user_role` | front_desk, operator, admin, doctor |

## 2. Tables

### `app_settings`

| Column | Type | Constraints | Description |
|---|---|---|---|
| key | VARCHAR(100) | PK | Setting name; must exist in settings_service.SETTINGS_REGISTRY. |
| value | JSONB | NOT NULL | JSON value applied over app/config.py at startup and on write. |
| updated_by | UUID | FK users.id ON DELETE SET NULL | User who last changed the setting. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

### `appointments`

| Column | Type | Constraints | Description |
|---|---|---|---|
| case_id | UUID | NOT NULL; FK intake_cases.id | References intake_cases. |
| doctor_id | UUID | NOT NULL; FK users.id | References users. |
| time_slot | TIMESTAMP WITH TIME ZONE | NOT NULL | Start instant, UTC-aware; rendered in Australia/Sydney. |
| status | enum appointment_status | NOT NULL | pending, confirmed, cancelled or completed. |
| duration_minutes | INTEGER | NOT NULL | Length; default 30. |
| appointment_type | enum appointment_type | NOT NULL | new_patient, follow_up, procedure or other. |
| location | VARCHAR(255) |  | Room or location. |
| reason | TEXT |  | Reason for visit. Not included in reminder emails. |
| internal_notes | TEXT |  | Staff-only notes. Not included in reminder emails. |
| reference_code | VARCHAR(16) | NOT NULL | Booking reference, APT- plus six characters, generated per row; shown to the patient in reminder emails. |
| notify_patient | BOOLEAN | NOT NULL | Whether the patient should be reminded. |
| reminder_sent_at | TIMESTAMP WITH TIME ZONE |  | Idempotency guard for the reminder sweep, the role draft_sent plays for replies. |
| notify_provider | BOOLEAN | NOT NULL | Whether the doctor should be notified. |
| series_id | UUID |  | Shared id of a repeating series booked in one request. |
| episode_id | UUID | INDEX; FK episodes.id ON DELETE SET NULL | Taken from the contact at booking (appointment_service.book_appointment). |
| id | UUID | PK | Primary key (UUID). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

Table-level: CheckConstraint ck_appointment_duration_positive; UniqueConstraint unq_appointment_reference_code.

### `approval_requests`

| Column | Type | Constraints | Description |
|---|---|---|---|
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| action_type | VARCHAR(100) | NOT NULL; INDEX | email.draft_reply or patient.assignment.suggested; selects the executor. |
| case_id | UUID | INDEX; FK intake_cases.id ON DELETE SET NULL | References intake_cases. |
| payload | JSONB | NOT NULL | What was proposed (draft text, email and task ids, reasons). |
| external_ref | VARCHAR(255) |  | Agent graph thread id when the agent paused here; used to resume it. |
| requested_by_id | UUID | FK users.id ON DELETE SET NULL | References users. |
| requested_by_label | VARCHAR(255) | NOT NULL | Label of the requester (agent or user). |
| status | enum approval_status | NOT NULL; INDEX | pending, approved or rejected. |
| decided_by_id | UUID | FK users.id ON DELETE SET NULL | References users. |
| decided_at | TIMESTAMP WITH TIME ZONE |  | When decided. |
| resolved_payload | JSONB |  | Approver's edits; only the draft text is honoured. |
| decision_notes | TEXT |  | Approver's note. |
| id | UUID | PK | Primary key (UUID). |

### `audit_events`

| Column | Type | Constraints | Description |
|---|---|---|---|
| id | UUID | PK | Primary key (UUID). |
| case_id | UUID | INDEX; FK intake_cases.id ON DELETE SET NULL | References intake_cases. |
| actor_id | UUID | INDEX; FK users.id ON DELETE SET NULL | References users. |
| actor_label | VARCHAR(255) | NOT NULL | Actor email or service label. |
| action | VARCHAR(100) | NOT NULL; INDEX | Dotted action name, e.g. email.sent; constrained by ck_audit_events_action_shape. |
| details | JSONB | NOT NULL | Event details as JSON. Never holds prompt text or tokens. |
| timestamp | TIMESTAMP WITH TIME ZONE | NOT NULL; INDEX | Client-assigned time; chain order uses sequence_number instead. |
| actor_role | VARCHAR(50) |  | Actor role at the time. |
| risk_score | INTEGER |  | 10, 50 or 90 from audit_service._compute_risk_score. |
| outcome | VARCHAR(20) |  | SUCCESS or BLOCKED. |
| ip_address | VARCHAR(45) |  | Client address from the request context. |
| session_id | VARCHAR(64) |  | Session id (sid claim of the JWT) of the request that wrote the event. |
| event_hash | VARCHAR(64) |  | SHA-256 over the predecessor hash and this row, set by trigger. |
| predecessor_hash | VARCHAR(64) |  | event_hash of the previous row by sequence_number. |
| sequence_number | BIGINT | server default | Server-assigned counter the hash chain is ordered by, so concurrent writers cannot reorder it. |

### `calls`

| Column | Type | Constraints | Description |
|---|---|---|---|
| case_id | UUID | NOT NULL; INDEX; FK intake_cases.id ON DELETE CASCADE | References intake_cases. |
| phone_number | VARCHAR(20) | NOT NULL | Caller ID, or the withheld marker. |
| transcript | TEXT |  | Transcript (typed, uploaded audio, or Whisper on voicemail). |
| status | enum call_status | NOT NULL | call_status value. |
| triage_id | UUID | INDEX; FK triage_results.id ON DELETE SET NULL | References triage_results. |
| routing_id | UUID | INDEX; FK routing_decisions.id ON DELETE SET NULL | References routing_decisions. |
| urgency_tier | enum triage_category |  | triage_category of a logged call. |
| target_queue | VARCHAR(100) |  | Queue name. |
| routing_overridden | BOOLEAN | NOT NULL | True after a staff override. |
| category | enum task_category |  | task_category from the shared classifier. |
| confidence | FLOAT |  | Classifier confidence. |
| target_role | enum user_role |  | Role whose queue it lands in. |
| kind | enum call_kind | NOT NULL; server default | logged or voicemail. |
| twilio_call_sid | VARCHAR(64) | UNIQUE | The row's key while a Twilio call is live, and the idempotency key for Twilio's retried callbacks. |
| twilio_recording_sid | VARCHAR(64) |  | Twilio recording id, deleted from Twilio after download. |
| twilio_deleted | BOOLEAN |  | None: never on Twilio (logged call, simulated voicemail). False: a delete failed and the sweep retries it. |
| audio_key | VARCHAR(255) |  | MinIO key of the stored audio; removed after the retention period. |
| keypad_dob | DATE |  | DOB entered on the keypad (DDMMYYYY). |
| keypad_intent | VARCHAR(20) |  | Menu choice. |
| urgent_pressed | BOOLEAN | NOT NULL; server default | Caller pressed 9 for urgent. |
| transcript_quality | JSONB |  | Whisper confidence figures and a low-quality flag. |
| id | UUID | PK | Primary key (UUID). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

### `chunks`

| Column | Type | Constraints | Description |
|---|---|---|---|
| id | UUID | PK | Primary key (UUID). |
| patient_id | UUID | INDEX | Patient the chunk belongs to; NULL marks an org-wide (clinic) chunk. No foreign key. |
| doc_type | TEXT | NOT NULL | Document type the chunk came from (see clinical_doc_type and the org doc types in app/rag/doc_scopes.py). |
| access_scope | TEXT | NOT NULL | general, restricted or sensitive. Filtered by app/rag/retrieval.py::_security_filter before any text reaches a model. |
| source_document_id | UUID | NOT NULL | Stable id of the source document (clinical_documents.id for uploaded files). No foreign key. |
| citation_tag | TEXT |  | Readable citation label, {patient_id_short}_{doc_type}. |
| chunk_index | INTEGER | NOT NULL | Position of the chunk inside its source document. |
| attachment_uri | TEXT |  | Pointer to a scan or image when the chunk is a report on one. Unused by current data. |
| content | TEXT | NOT NULL | The chunk text. |
| embedding | VECTOR(512) | NOT NULL | vector(512), nomic-embed-text-v1 truncated to 512 dimensions, cosine distance, HNSW index. |
| search_vector | TSVECTOR | server default; GENERATED | Generated tsvector of content for Postgres full-text search (hybrid retrieval). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |

### `clinical_documents`

| Column | Type | Constraints | Description |
|---|---|---|---|
| patient_id | UUID | NOT NULL; FK patients.id | References patients. |
| doc_type | enum clinical_doc_type | NOT NULL | clinical_doc_type value; decides the access_scope of its chunks. |
| filename | VARCHAR(255) | NOT NULL | Original file name. |
| content_type | VARCHAR(100) | NOT NULL | MIME type; uploads must be PDF. |
| size_bytes | INTEGER | NOT NULL | File size in bytes. |
| storage_key | TEXT | NOT NULL | Object key in the MinIO clinical-documents bucket. |
| extracted_text | TEXT | NOT NULL | Text extracted from the PDF text layer (no OCR). |
| uploaded_by | UUID | NOT NULL; FK users.id | User who uploaded it. |
| ingested_at | TIMESTAMP WITH TIME ZONE |  | When it was chunked and embedded; NULL until ingested. |
| id | UUID | PK | Primary key (UUID). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

### `consent_records`

| Column | Type | Constraints | Description |
|---|---|---|---|
| case_id | UUID | NOT NULL; INDEX; FK intake_cases.id ON DELETE CASCADE | References intake_cases. |
| status | enum consent_status | NOT NULL | pending, captured, withdrawn or not_required (not_required is never set by code). |
| captured_at | TIMESTAMP WITH TIME ZONE |  | When captured. |
| consent_type | VARCHAR(50) | NOT NULL | Which consent form. |
| notes | TEXT |  | Free-text notes. |
| form_snapshot | JSONB |  | The clauses, ticks and signature as presented and captured. |
| episode_id | UUID | INDEX; FK episodes.id ON DELETE SET NULL | Taken from the contact when the record is created (consent_service). |
| id | UUID | PK | Primary key (UUID). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

### `doctor_patient_assignments`

| Column | Type | Constraints | Description |
|---|---|---|---|
| doctor_id | UUID | PK; FK users.id | References users. |
| patient_id | UUID | PK; FK patients.id | References patients. |
| assigned_by | UUID | NOT NULL; FK users.id | Who made the assignment. |
| assigned_at | TIMESTAMP WITH TIME ZONE | NOT NULL | When. |

### `email_conversations`

| Column | Type | Constraints | Description |
|---|---|---|---|
| case_id | UUID | NOT NULL; UNIQUE; FK intake_cases.id ON DELETE CASCADE | References intake_cases. |
| patient_id | UUID | FK patients.id | NULL until someone is identified: a first email with no name has no patient to file anything under (Patient.name is NOT NULL). |
| original_intent | VARCHAR(64) | NOT NULL | The intent of the email that opened the conversation. |
| origin_email_id | UUID | FK emails.id ON DELETE SET NULL | References emails. |
| stage | VARCHAR(32) | NOT NULL | A plain string, not a DB enum: adding a stage is then not a migration. |
| preferred_day | DATE |  | Day the patient asked for. |
| offered_slots | JSONB | NOT NULL | [{"doctor_id", "doctor_name", "start"}], start an ISO UTC instant. |
| last_outbound_text | TEXT |  | Last text actually sent in the conversation. |
| clarifications | INTEGER | NOT NULL | Failed turns (unclear, unoffered time, changed DOB). One gets a clarifying reply; the second hands the case to staff. |
| verification_sent_at | TIMESTAMP WITH TIME ZONE |  | When the identity request went out; once per case. |
| confirmed_email_id | UUID | FK emails.id ON DELETE SET NULL | The patient's written confirmation of an offered time: the email that made a provisional patient bookable (patient_service.assert_bookable). |
| appointment_id | UUID | FK appointments.id ON DELETE SET NULL | References appointments. |
| form_token_hash | VARCHAR(64) | UNIQUE | The registration form link (patient_form_service). Only the hash is kept here; the link itself is in the email that was sent. |
| form_sent_at | TIMESTAMP WITH TIME ZONE |  | When the registration link went out. |
| form_submitted_at | TIMESTAMP WITH TIME ZONE |  | When the form was submitted; a link works once. |
| id | UUID | PK | Primary key (UUID). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

### `emails`

| Column | Type | Constraints | Description |
|---|---|---|---|
| case_id | UUID | NOT NULL; INDEX; FK intake_cases.id ON DELETE CASCADE | References intake_cases. |
| sender | VARCHAR(255) | NOT NULL | From address. |
| recipient | VARCHAR(255) | NOT NULL | To address. |
| subject | VARCHAR(500) | NOT NULL | Subject. |
| body | TEXT | NOT NULL | Body text (HTML stripped for Outlook mail). |
| received_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Mailbox receipt time, or ingest time for direct ingest. |
| external_id | VARCHAR(255) |  | Provenance for mail pulled from an external mailbox. |
| external_source | VARCHAR(50) |  | outlook for polled mail. |
| sender_name | VARCHAR(255) |  | Threading and reply parsing (email_conversation_service). |
| internet_message_id | VARCHAR(998) | INDEX | RFC 5322 Message-ID. A patient's reply carries it in References, which is how the reply finds its case. |
| in_reply_to | TEXT |  | In-Reply-To header, used to link a reply to its conversation. |
| references_header | TEXT |  | References header, used for the same purpose. |
| new_text | TEXT |  | The part of the body the sender wrote in this message, without the quoted history underneath (Graph's uniqueBody). |
| auto_submitted | BOOLEAN | NOT NULL; server default | An out-of-office or other machine reply. Never answered automatically: two auto-responders answering each other is a mail loop. |
| id | UUID | PK | Primary key (UUID). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

### `episodes`

| Column | Type | Constraints | Description |
|---|---|---|---|
| patient_id | UUID | NOT NULL; FK patients.id | References patients. |
| title | VARCHAR(255) | NOT NULL | Case title, defaulting to the category of the first contact. |
| status | enum episode_status | NOT NULL | open or closed. |
| doctor_id | UUID | FK users.id | NULL only when no active doctor existed to give it. |
| opened_at | TIMESTAMP WITH TIME ZONE | NOT NULL | When the case opened. |
| opened_by | UUID | FK users.id | The agent account for cases opened automatically. |
| closed_at | TIMESTAMP WITH TIME ZONE |  | When it closed. |
| closed_by | UUID | FK users.id | Who closed it. |
| outcome_note | TEXT |  | Note required on close. |
| last_activity_at | TIMESTAMP WITH TIME ZONE | NOT NULL | What the close nudge (case_nudge) measures staleness by. |
| nudge_snoozed_until | TIMESTAMP WITH TIME ZONE |  | Keep open pushes the next close nudge to this time. |
| id | UUID | PK | Primary key (UUID). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

### `human_review_tasks`

| Column | Type | Constraints | Description |
|---|---|---|---|
| case_id | UUID | FK intake_cases.id ON DELETE CASCADE | The contact the item is about. NULL only for an item about a case (CASE_CLOSE), which carries episode_id instead. |
| episode_id | UUID | FK episodes.id ON DELETE CASCADE | References episodes. |
| triage_id | UUID | FK triage_results.id ON DELETE SET NULL | References triage_results. |
| task_type | enum task_type | NOT NULL | Review kind (task_type enum). |
| status | enum task_status | NOT NULL | pending, in_progress, completed, cancelled or escalated. |
| target_role | enum user_role | INDEX | Owning role. |
| assigned_to | UUID | FK users.id ON DELETE SET NULL | Owning user, when assigned. |
| notes | TEXT |  | Reason the item exists, or reviewer notes. |
| priority | enum task_priority | NOT NULL | low, medium or high; high has a 4 h SLA, others 24 h. |
| approval_id | UUID | INDEX; FK approval_requests.id ON DELETE SET NULL | The held draft's approval (DRAFT_APPROVAL only): approving or rejecting it, from either screen, closes this item (approval_service). |
| inbox_task_id | UUID | FK tasks.id ON DELETE SET NULL | The inbox message the item is about, so the two screens find each other. |
| details | JSONB |  | Kind-specific: identity candidates, the classifier's category, the failed stage, who escalated it and why. |
| id | UUID | PK | Primary key (UUID). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

Table-level: Index uq_human_review_open_per_message (inbox_task_id, task_type) UNIQUE; Index uq_human_review_open_per_episode (episode_id, task_type) UNIQUE.

### `intake_cases`

| Column | Type | Constraints | Description |
|---|---|---|---|
| patient_id | UUID | FK patients.id | References patients. |
| patient_name | VARCHAR(255) |  | Name as given on contact, before or without a patient link. |
| contact_reason | TEXT | NOT NULL | Subject line or reason for contact. |
| contact_channel | VARCHAR(50) | NOT NULL | email, call, voicemail or a staff channel. |
| notes | TEXT |  | Free-text notes. |
| status | enum intake_status | NOT NULL | intake_status value. |
| episode_id | UUID | INDEX; FK episodes.id ON DELETE SET NULL | The case (episode of care) this contact belongs to. NULL for anything that is not a known patient's clinical message. |
| id | UUID | PK | Primary key (UUID). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

### `medications`

| Column | Type | Constraints | Description |
|---|---|---|---|
| patient_id | UUID | NOT NULL; INDEX; FK patients.id ON DELETE CASCADE | References patients. |
| name | VARCHAR(255) | NOT NULL | Medicine name. Never placed in an agent email. |
| dosage | VARCHAR(100) |  | Dose. |
| frequency | VARCHAR(100) |  | Frequency. |
| prescribed_by_id | UUID | FK users.id ON DELETE SET NULL | SET NULL, not CASCADE: a doctor leaving the clinic must not delete the record that a medication was prescribed. |
| prescribed_on | DATE | NOT NULL | Date prescribed. |
| last_review_date | DATE |  | Nullable: a medication carried over from another practice may never have been reviewed here. |
| repeats_remaining | INTEGER |  | Repeats left. |
| status | enum medication_status | NOT NULL; INDEX | active, discontinued or expired. |
| notes | TEXT |  | Free-text notes. |
| id | UUID | PK | Primary key (UUID). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

### `patients`

| Column | Type | Constraints | Description |
|---|---|---|---|
| mrn | VARCHAR(50) | NOT NULL; UNIQUE | Medical record number, generated at registration, unique. |
| name | VARCHAR(255) | NOT NULL | Full name. |
| dob | DATE |  | Nullable since migration 0031: a patient identified from an inbound message has a name and a contact address and nothing else. |
| gender | enum gender |  | male, female or non_binary. |
| status | enum patient_status | NOT NULL | pending until the profile is complete, then active; inactive is set by staff. |
| address | VARCHAR(255) |  | Street address. |
| indigenous_status | VARCHAR(255) |  | Aboriginal and Torres Strait Islander status as recorded. |
| preferred_language | VARCHAR(255) |  | Preferred language. |
| phone | VARCHAR(255) |  | Contact phone. Used by identity matching and voicemail caller ID matching. |
| email | VARCHAR(255) |  | Contact email. Agent mail about appointments goes only to this address. |
| emergency_contact_name | VARCHAR(255) |  | Emergency contact name. |
| emergency_contact_phone | VARCHAR(255) |  | Emergency contact phone. |
| preferred_communication | VARCHAR(255) |  | Preferred contact method. |
| best_time_to_contact | VARCHAR(255) |  | Preferred contact time. |
| known_conditions | TEXT |  | Known conditions as typed by staff. Never read by the agent. |
| current_medications | TEXT |  | Medications as typed by staff at registration. |
| allergies | TEXT |  | Allergies as typed by staff. |
| insurance_provider | VARCHAR(255) |  | Private health fund. |
| policy_number | VARCHAR(255) |  | Health fund policy number. |
| group_number | VARCHAR(255) |  | Health fund group number. |
| insurance_expiry | DATE |  | Health fund expiry date. |
| medicare_number | VARCHAR(255) |  | Medicare number. |
| concession_card | VARCHAR(255) |  | Concession card number. |
| is_provisional | BOOLEAN | NOT NULL; INDEX; server default | True for a patient known only from an inbound message; blocks booking, records and prescription agents until staff promote the record. |
| purged_at | TIMESTAMP WITH TIME ZONE |  | Set when an unclaimed provisional row is anonymised in place after settings.provisional_patient_ttl_days. |
| preferred_doctor_id | UUID | FK users.id | Honoured by assignment_service.ensure_doctor while that doctor is active. |
| id | UUID | PK | Primary key (UUID). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

### `routing_decisions`

| Column | Type | Constraints | Description |
|---|---|---|---|
| case_id | UUID | NOT NULL; INDEX; FK intake_cases.id ON DELETE CASCADE | References intake_cases. |
| triage_id | UUID | NOT NULL; INDEX; FK triage_results.id ON DELETE CASCADE | References triage_results. |
| action | enum routing_action | NOT NULL | routing_action value. |
| target_queue | VARCHAR(100) | NOT NULL | Queue name. |
| escalated | BOOLEAN | NOT NULL | Whether routing escalated. |
| id | UUID | PK | Primary key (UUID). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

### `task_comments`

| Column | Type | Constraints | Description |
|---|---|---|---|
| task_id | UUID | NOT NULL; INDEX; FK tasks.id ON DELETE CASCADE | References tasks. |
| author_id | UUID | NOT NULL; INDEX; FK users.id ON DELETE CASCADE | References users. |
| body | TEXT | NOT NULL | Comment text. |
| id | UUID | PK | Primary key (UUID). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

### `tasks`

| Column | Type | Constraints | Description |
|---|---|---|---|
| case_id | UUID | NOT NULL; INDEX; FK intake_cases.id ON DELETE CASCADE | References intake_cases. |
| call_id | UUID | INDEX; FK calls.id ON DELETE CASCADE | References calls. |
| email_id | UUID | FK emails.id ON DELETE SET NULL | The email this task was opened for. A case holds the whole thread, so case_id alone cannot say which message a reply's task is about. |
| assigned_to | UUID | INDEX; FK users.id ON DELETE SET NULL | User working the task. |
| source | enum task_source | NOT NULL | email or call. |
| priority | enum task_priority | NOT NULL | low, medium, high or urgent; set from the routing gate. |
| status | enum task_status | NOT NULL | pending, in_progress, completed or escalated. |
| target_queue | VARCHAR(100) |  | Queue name. |
| handover_context | TEXT |  | Why the task waits for a person, in staff wording. |
| category | enum task_category |  | task_category from the classifier. |
| target_role | enum user_role | INDEX | Role whose inbox shows it. |
| draft_text | TEXT |  | Current draft or sent reply. |
| draft_approval_id | UUID | FK approval_requests.id ON DELETE SET NULL | References approval_requests. |
| draft_sent | BOOLEAN | NOT NULL | True once a reply was delivered; the duplicate-send guard. |
| read_at | TIMESTAMP WITH TIME ZONE |  | When marked read. |
| deleted_at | TIMESTAMP WITH TIME ZONE |  | Soft delete time. |
| deleted_by | UUID | FK users.id ON DELETE SET NULL | Who deleted it. |
| id | UUID | PK | Primary key (UUID). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

### `triage_results`

| Column | Type | Constraints | Description |
|---|---|---|---|
| case_id | UUID | NOT NULL; INDEX; FK intake_cases.id ON DELETE CASCADE | References intake_cases. |
| category | enum triage_category | NOT NULL | triage_category from the manual POST /triage rules. |
| confidence | FLOAT | NOT NULL | Rule confidence (0.4 to 0.9). |
| rationale | TEXT | NOT NULL | Why that category. |
| routed | BOOLEAN | NOT NULL | Whether a routing decision followed. |
| id | UUID | PK | Primary key (UUID). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

### `user_permission_grants`

| Column | Type | Constraints | Description |
|---|---|---|---|
| user_id | UUID | PK; FK users.id | References users. |
| permission | VARCHAR(50) | PK | Permission string granted on top of the role (only those in GRANTABLE apply). |
| granted_by | UUID | NOT NULL; FK users.id | Admin who granted it. |
| granted_at | TIMESTAMP WITH TIME ZONE | NOT NULL | When it was granted. |

### `users`

| Column | Type | Constraints | Description |
|---|---|---|---|
| email | VARCHAR(255) | NOT NULL; UNIQUE; INDEX | Sign-in email, unique. |
| hashed_password | VARCHAR(255) | NOT NULL | bcrypt hash of the password. |
| full_name | VARCHAR(255) | NOT NULL | Display name. |
| department | VARCHAR(255) |  | Free-text department; for doctors, the special interest from the clinic roster. |
| role | enum user_role | NOT NULL | front_desk, operator, admin or doctor. |
| is_active | BOOLEAN | NOT NULL | False blocks sign-in. Users with audit rows are deactivated, never deleted. |
| id | UUID | PK | Primary key (UUID). |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Row creation time. |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL | Last update time. |

## 3. Objects outside the models

| Object | Kind | Purpose |
|---|---|---|
| `vector_store` | Table (created by migration 0003, dropped by migration 0041 on 18 Oct) | Unused; no longer exists on a migrated database |
| `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations` | Tables (LangGraph) | Agent graph checkpoints |
| `block_audit_modification()` | Function | Raises on UPDATE or DELETE of `audit_events` |
| `compute_audit_event_hash()` | Function | Sets `event_hash` and `predecessor_hash` |
| `verify_audit_chain()` | Function | Recomputes the chain; returns validity, count, first break |
| `audit_events_no_update`, `_no_delete`, `_no_truncate`, `_compute_hash` | Triggers | Append-only and hash chain |
| `excl_doctor_overlap` | Exclusion constraint | No overlapping live appointments per doctor |
| `chunks_embedding_hnsw_idx` | HNSW index | Vector search |
