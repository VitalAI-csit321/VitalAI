# VitalAI backend function reference

Every public function in the backend, by module. Purposes come from the code's docstrings; purposes for functions without a docstring were written from their code.

## 1. Agents

**`app/agents/checkpointer.py`**: Postgres checkpointer for the agent graph.

| Function | Arguments | Purpose |
|---|---|---|
| `conninfo` | database_url | The app's SQLAlchemy URL rewritten as a plain libpq URL for psycopg. |
| `open_checkpointer` | none | One connection for the lifetime of one graph run. |

**`app/agents/graph.py`**: The agent graph: thread identity, run context, nodes, and how a run is invoked.

| Function | Arguments | Purpose |
|---|---|---|
| `thread_id` | channel, source_id | One thread per inbound message, never per case. |
| `run_config` | tid | Returns the LangGraph run configuration that binds a run to its thread ID. |
| `make_context` | session_factory | Builds the agent run context with the session factory and the agent's system user. |
| `create_approval` | state, runtime | Write the ApprovalRequest (and its audit event). Runs exactly once. |
| `await_approval` | state | Pause until a human decides. Calls interrupt() and nothing else. |
| `route_intent` | state | Which agent handles this message. Pure function of state. |
| `route_after_consent` | state | Voicemail never drafts: urgent ones already have their script, and the rest go to caller matching. |
| `after_voicemail_identity` | state | Chooses the next agent step after a voicemail caller's identity check: booking, onboarding or callback. |
| `after_booking` | state | Chooses the next graph step after booking: callback for voicemail, otherwise draft or stop on a hold. |
| `after_own_appointment` | state | It sent its own email (to the address on the patient's record, not as a reply); anything it passed on is routed the way it was before the node existed. |
| `route_identity` | state | Routes after the reply gate on intent, identity outcome and provisional status. |
| `after_conversation` | state | Chooses the next graph step after the conversation node: stop, re-check identity, book or draft. |
| `auto_send_or_approve` | state | The same predicate draft_reply uses, plus the rule that a HIGH risk tier (email_service.reply_risk_tier) always reaches a human. |
| `after_critic` | state | Chooses the next graph step after the critic: guardrail, another draft, or escalation. |
| `build_graph` | none | Builds the LangGraph agent graph, registering each node with error guarding and wiring the routing edges. |
| `run` | tid, graph_input | Start or resume one thread against the Postgres checkpointer. |
| `start` | task_id, email_id, actor_id, gate, confidence | Run the reply graph for one ingested email. |
| `rerun_after_review` | review_id | A person answered the Review Queue item that stopped an email (linked the sender to a patient, or confirmed or changed its category): run the agent on that email again, so the patient is answered without writing again. |
| `start_voicemail` | task_id, call_id, urgent | Run the graph for one processed voicemail. |
| `resume` | tid, decision | Scheduled entry point for an approve/reject decision. |

**`app/agents/nodes.py`**: Email reply pipeline nodes.

| Function | Arguments | Purpose |
|---|---|---|
| `load` | state, runtime | Populate state from the rows ingest_email already committed. |
| `consent` | state, runtime | Read-only. Email cases usually have no consent record at all, and that must never block a reply: this records, it does not gate. |
| `urgent_notice` | state, runtime | An email held as urgent (route_intent): tell the sender it was received and where to go in an emergency, then leave it for a person as before. |
| `reply_gate` | state, runtime | Checks whether an email deserves a reply and records the verdict and question flags in state. |
| `identity` | state, runtime | Who sent this. Recorded for every case; route_identity decides whether the outcome blocks. A general intent makes no LLM call. |
| `onboarding` | state, runtime | A stranger asking to join or to book: create the provisional patient and record their implied consent, once. The reply itself is drafted by the draft node, so a critic redraft does not repeat this. |
| `booking` | state, runtime | The patient's own doctor, and the next free times in their diary. |
| `records` | state, runtime | Consent decides which records acknowledgement is drafted, and nothing else. |
| `prescription` | state, runtime | Read the medication history, raise an internal request and acknowledge. |
| `conversation` | state, runtime | One turn of an email conversation (email_conversation_service): the first appointment request, or any reply linked to an open conversation. |
| `book` | state, runtime | Turn 3: book the offered time the patient confirmed, if their record is bookable and the time is still free, then confirm it. Otherwise a human (email_conversation_service.book_choice). |
| `own_appointment` | state, runtime | The email is about an appointment the sender already has (own_appointment_service): say when it is, or ask them to confirm a cancel or a move with the code this sends. |
| `clinical_info` | state, runtime | Health information sent for a doctor to see (reply gate): nothing is generated. |
| `request_verification` | state, runtime | A patient-specific inquiry from a sender who cannot be identified. |
| `form_link` | state, runtime | An unknown sender asking to book or to sign up: a link to the registration form instead of a request to email their details (patient_form_service). |
| `identity_hold` | state, runtime | Holds the case for staff review when the sender's identity cannot be confirmed. |
| `draft` | state, runtime | First draft, or a regeneration after the critic rejected the last one. A regeneration carries the critic's reason into the prompt and counts toward revision_count, which the edge after critic caps. |
| `critic` | state | Runs the critic over the draft reply and records a pass or reject verdict. |
| `escalate` | state, runtime | Records the critic's rejection of a drafted reply as an escalation for staff and marks the case escalated. |
| `guardrail` | state, runtime | Runs the output guardrail on the draft reply and holds the task undrafted if blocked. |
| `risk` | state | A HIGH risk tier sends the draft to approval whatever the auto-send rule says. |
| `auto_send` | state, runtime | Deliver through the one shared send path. A failed delivery routes to create_approval with the reason, so the draft reaches the human queue. |
| `dispatch` | state, runtime | Never sends. The approvals route's executor already ran deliver_reply before scheduling this resume; this reads the result and records it. |
| `voicemail_identity` | state, runtime | Caller ID + keypad DOB, one patient or nobody. The match is probable: it goes into state and the script, never onto the case. |
| `voicemail_onboarding` | state, runtime | An unknown caller asking to book or join: the provisional patient that email onboarding would create. |
| `callback` | state, runtime | Terminal for voicemail: the callback script on the Task. |

**`app/agents/state.py`**: Graph state and run context.


## 2. Services

**`app/services/appointment_reminders.py`**: Remind a patient the day before their appointment.

| Function | Arguments | Purpose |
|---|---|---|
| `render_reminder` | appointment, name | When, where, the reference, and how to change it. Nothing else. |
| `send_due_reminders` | actor | One sweep cycle. Returns the ids of the appointments it reminded. |
| `remind_once` | none | Runs one reminder sweep that sends any appointment reminders now due. |
| `run_reminders` | none | Sweep until cancelled. One bad cycle must not kill the loop: nothing restarts it short of an app restart (same policy as the purge sweep and the Outlook poller). |

**`app/services/appointment_service.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `is_clinic_day` | day | A weekday that is not a public holiday in the clinic's state. The clinic is closed on those, and email booking offered Labour Day slots. |
| `assert_within_clinic_hours` | start, duration_minutes | Refuse a time the clinic is closed, read in the clinic's timezone. |
| `book_appointment` | doctor_id, case_id, time_slot, actor, duration_minutes, appointment_type, location, reason, internal_notes, status, notify_patient, notify_provider, series_id, commit, allow_provisional, enforce_hours | Books an appointment after checking the doctor, case, patient status, access and clinic hours. |
| `book_appointment_series` | payload, actor, enforce_hours | Book one appointment, or a linked series when payload.repeat is set. |
| `list_appointments` | actor, doctor_id, patient_id, date_from, date_to, appointment_type, status, search, limit, offset | Lists appointments with optional filters and paging, restricting doctors to their assigned patients. |
| `reschedule_appointment` | appointment_id, new_time_slot, actor, scoped_doctor_id, enforce_hours | Moves an appointment to a new time, rejecting cancelled bookings and clashes, and logs the change. |
| `update_appointment` | appointment_id, payload, actor, scoped_doctor_id, enforce_hours | Updates an accessible appointment, validating status and doctor changes and rejecting cancelled or completed ones. |
| `complete_appointment` | appointment_id, actor, scoped_doctor_id | Marks a confirmed appointment as completed and records the change in the audit log. |
| `cancel_appointment` | appointment_id, actor, scoped_doctor_id, cancel_reason, notify_patient | Cancels an appointment the user may access, rejecting repeat cancellations and recording an audit event. |
| `serialize_appointment` | appointment | Attach the three joined labels and the derived end_time. |
| `serialize_many` | appointments | Converts appointments to output records, adding doctor names and patient names and MRNs in bulk. |
| `clinic_date` | instant | The clinic-local calendar day an instant falls on. |
| `clinic_day_window` | day, days | The [start, end) instants covering `days` clinic-local days from `day`. |
| `get_calendar_month` | actor, year, month, doctor_id | Returns a month calendar of visible appointments grouped by day, with summary statistics. |
| `get_calendar_markers` | actor, year, month, doctor_id | Returns per-day appointment counts for a month, used as calendar markers. |
| `get_day_view` | actor, day, doctor_id | Returns one clinic day's appointments with status counts, booked minutes and each doctor's appointment load. |
| `get_availability` | actor, doctor_id, day, slot_minutes | Returns a doctor's bookable slots for a day within clinic hours, marking slots that clash. |
| `get_appointment_detail` | actor, appointment_id, scoped_doctor_id | Returns an appointment's full detail, including patient summary, consent status and audit history. |

**`app/services/appointment_suggestion_service.py`**: Propose appointment slots. Never books one.

| Function | Arguments | Purpose |
|---|---|---|
| `suggest_slots` | actor, case_id, doctor_id, from_date, count, duration_minutes, search_days | Walk forward from from_date and write the first `count` free slots as pending suggestions. Returns fewer than `count` if the window has fewer. |

**`app/services/approval_service.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `create_approval_request` | action_type, payload, case_id, requested_by, external_ref | Creates an approval request, opens a review item for draft replies, and audits it. |
| `approve` | approval_id, decided_by, resolved_payload, notes | Approves a pending approval request under a row lock, recording the decision and closing its review item. |
| `reject` | approval_id, decided_by, notes | Rejects a pending approval request, records the decision and audit event, and closes its review item. |
| `ensure_approved` | request | Raise unless `request` has been approved. |
| `list_approvals` | status, action_type, case_id, limit, offset | Lists approval requests filtered by status, action type or case, with a total count. |
| `get_approval` | approval_id | Returns the approval request with the given id, or nothing if absent. |

**`app/services/assignment_service.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `assign_patient` | doctor_id, patient_id, actor | Assigns a patient to a doctor after validating both, rejecting duplicates and recording an audit event. |
| `unassign_patient` | doctor_id, patient_id, actor | Removes a doctor's assignment to a patient and logs it, returning whether one existed. |
| `list_assignments` | doctor_id | Lists the patient assignments held by a given doctor. |
| `ensure_doctor` | patient, actor | A registered patient with no active doctor gets one now, their preference while that doctor is active, else the least-loaded active doctor. |
| `change_doctor` | patient, doctor_id, actor | Staff change who the patient's doctor is. |

**`app/services/audit_service.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `risk_level_from_score` | score | Converts a numeric risk score into a Low, Medium or High risk label. |
| `record_event` | action, case_id, actor, actor_label, details | Append a new audit event and flush it to the session. |
| `get_events_for_case` | case_id | Returns all audit events for a case in timestamp order. |
| `list_events` | actor_id, action, risk_level, outcome, case_id, from_time, to_time, limit, offset | Lists audit events with optional filters for actor, action, risk level, outcome, case and time. |
| `get_event_by_id` | event_id | Returns a single audit event by its ID. |
| `verify_chain` | none | Runs the database audit chain check and returns validity, count and first break. |

**`app/services/booking_service.py`**: Proposing appointment times to a patient we have identified.

| Function | Arguments | Purpose |
|---|---|---|
| `doctor_for_patient` | patient_id | The patient's longest-standing active doctor, or None if they have none. |
| `doctor_for_episode` | episode | Who does a case's doctor work: its doctor while they are active and still assigned to the patient, else the patient's doctor. inbox_service._scoped applies the same rule in SQL. |
| `doctor_for_contact` | contact | Who does the doctor work on this message: its case's (doctor_for_episode), or the patient's when it is in no case. |
| `find_slots` | actor, doctor_id, from_date, count, horizon_days | The next `count` free slots, scanning clinic-local days from tomorrow. |
| `format_slot` | instant | "Tuesday 1 September at 8:00am", in clinic local time. |
| `titled` | doctor_name | Doctor names are stored both ways: seeded staff without the title, the demo corpus's doctors as "Dr Aisha Rahman". Title them once. |
| `draft_booking_reply` | name, doctor_name, slots | The proposal. A template, never a generated one, and it promises nothing: the times are offered, the patient picks, a human confirms. |
| `doctor_pool` | patient_id, doctor_name, specialisation, exclude | (first choice, fallback). None when the patient asked for a doctor or specialisation nobody active matches: that is a question for staff, not a reason to offer someone else. |
| `free_on_day` | actor, doctors, day, part_of_day | Every free start time that day across the doctors, earliest first, one doctor per time (the first in `doctors` order wins, so an assigned doctor is preferred). Weekends and times already past are never free. |
| `offer_times` | actor, pool, day, part_of_day | The requested day if it has anything free (first-choice doctors, then the fallback), otherwise the nearest days that do, closest first, never in the past. Empty means nothing within NEAREST_SPAN_DAYS either side. |

**`app/services/call_service.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `create_call` | payload, actor | Creates a manually entered call record, opening a new contact if no case is given, and audits it. |
| `get_call` | call_id | Returns the call with the given ID, or None if it does not exist. |
| `list_calls` | none | Lists every recorded call, with the newest first. |
| `route_call` | call_id, payload, actor | Classifies a call transcript, routes it to a role and updates its task. |
| `override_call_routing` | call_id, payload, actor | Overrides a routed call's category and target role with a staff choice and records the change. |
| `escalate_call` | call_id, payload, actor | Escalates a routed call with a transcript by marking its task urgent and recording handover context. |

**`app/services/case_nudge.py`**: The close nudge: a quiet case is put to its doctor to close.

| Function | Arguments | Purpose |
|---|---|---|
| `nudge_due` | actor | Open one case_close item per qualifying case, and commit. |
| `nudge_once` | none | Runs one sweep that asks staff whether quiet cases can be closed. |
| `run_case_nudges` | none | Sweep until cancelled. One bad cycle must not kill the loop (same policy as the reminder and purge sweeps). |

**`app/services/clinical_document_service.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `upload_document` | patient_id, doc_type, filename, content_type, file_bytes, actor | Validates and stores an uploaded clinical PDF, extracting its text for later retrieval. |
| `ingest_document` | document_id, actor | Chunks and embeds a clinical document once, storing the chunks for retrieval and recording an audit event. |
| `get_document` | document_id | Returns a clinical document by ID after checking its patient is not provisional. |
| `list_documents_for_patient` | patient_id | Lists a non-provisional patient's clinical documents, newest first. |
| `download_document_bytes` | document | Downloads a clinical document's file bytes from object storage. |

**`app/services/consent_service.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `create_consent_record` | case_id, actor, consent_type, notes, form_snapshot | Creates a pending consent record for a case, filing it under the case's episode and auditing it. |
| `get_consent_for_case` | case_id | Returns the most recent consent record for an intake case, if any. |
| `list_consents_for_patient` | patient_id | All consent records across every case for this patient - a reused case can carry more than one consent record over time, unlike get_consent_for_case() which only ever returns the latest per case. |
| `list_consent_queue` | limit, offset | Every consent record, newest first, with the name of the patient on its case. One query rather than a lookup per row. |
| `capture_consent` | consent_id, actor, form_snapshot | Captures a pending consent record, audits it and escalates for review if items are unchecked. |
| `verify_online_consent` | consent_id, actor, checks, signature | Staff have seen ID: the patient's online consent becomes captured. |
| `update_consent_checklist` | consent_id, actor, form_snapshot | Let staff finish ticking a consent's checklist after it landed in review (some items were left unchecked at capture time). Only valid on an already-captured record - the initial capture uses capture_consent(). |
| `withdraw_consent` | consent_id, actor | Withdraws a pending or captured consent record and logs the withdrawal in the audit trail. |

**`app/services/content_classifier.py`**: Shared LLM content classifier (FR-EMAIL-01), used by both email and calls so both feed the routing gate the same categories.

| Function | Arguments | Purpose |
|---|---|---|
| `from_intent_check` | reason | Checks whether a classification reason came from the intent-check second opinion or disagreement. |
| `classify_content` | llm, text, actor, channel, reasons | Classify email/call content into a TaskCategory with a confidence score. |

**`app/services/doctor_service.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `list_doctors` | search | Lists active doctors ordered by name, optionally filtered by a name search. |

**`app/services/doctor_suggestion.py`**: Suggests a doctor when a patient has none assigned (FR-GOV-01, FR-TASK-02).

| Function | Arguments | Purpose |
|---|---|---|
| `suggest_doctor_for_patient` | patient_id | Suggest the doctor with the fewest current patient assignments. |

**`app/services/draft_critic.py`**: Deterministic draft critic.

| Function | Arguments | Purpose |
|---|---|---|
| `drop_placeholder_lines` | draft | Removes lines that are only template placeholders from a drafted reply. |
| `critique` | draft, branch | None if the draft passes, otherwise the reason it was rejected. |

**`app/services/email_conversation_service.py`**: Multi-turn email on one case: verification requests and the booking flow.

| Function | Arguments | Purpose |
|---|---|---|
| `enabled` | none | Returns whether the email booking conversation feature is switched on. |
| `can_auto_reply` | email | Never answer a machine: two auto-responders answering each other is a mail loop. |
| `find_mrn` | text | Finds the first Medicare record number in a piece of text and returns it in upper case. |
| `find_case_for_reply` | sender, in_reply_to, references | The case an inbound email continues, or None for a new one. |
| `open_for_case` | case_id | Returns the email conversation for a case only while it is still at an open stage. |
| `get_or_create` | case_id, intent, origin_email_id, patient_id, stage | Returns the email conversation for a case, creating one if none exists. |
| `named_weekday` | day, text, today | The model resolves "next Wednesday" badly (today, or even yesterday, in every black-box sample). When the patient named exactly one weekday and the model's day is not that weekday, take the next one after today. |
| `slot_named_in` | text, slots | The offered slot the patient's own words pick out, or None when they do not pick exactly one. Beats the model's chosen_time: gemma2:2b read "The second one please" as the sixth slot and 10:30am got booked. |
| `extract` | llm, email, conversation, actor, earlier | None when the input guardrail blocked the reply. Unparseable output is an empty extraction (intent unclear, confidence 0), never an error. |
| `verification_text` | none | Names nobody and repeats nothing from the inquiry: whoever reads this inbox may not be who the clinic thinks. |
| `clinical_info_text` | name, doctor | To someone who sent readings or other health information. Fixed, so no model comments on what they sent. |
| `urgent_notice_text` | none | To the sender of an email held as urgent. |
| `ask_details_text` | name, missing, mrn, day_known | Builds the email text asking a patient for the details needed to book. |
| `offer_payload` | days | The offered times as record_sent stores them. UTC instants, so the stored value survives any backend that drops the offset (SQLite does). |
| `offer_text` | name, requested, days, missing | Builds the email text offering available appointment slots and listing any details still needed before booking. |
| `registered_text` | name, mrn, requested, days | After the registration form: the MRN, then times, a request for a day, or word that staff will find a time. |
| `confirmation_text` | name, start, doctor, first_visit, moved_from | Builds the patient email confirming a booked appointment, with first-visit and rescheduling notes. |
| `clarify_text` | reason, conversation | Always "Hello,": a changed date of birth may mean a different person is replying, so no clarification names anyone. |
| `handle_turn` | llm, conversation, email, actor, first_turn, known | Read the reply, update the record, decide. Audits the raw extraction and the decision. Commits. |
| `hand_back` | case_id, text | A person replied by hand to a conversation handed to staff: they have answered what the agent could not, so the agent takes the patient's next reply, with the person's words as the clinic's last message. |
| `record_sent` | conversation_id, text, next_stage, offer, verification, form_link | After a reply really went out: what the patient was shown is now what the next turn is checked against. Never before, so a reply that failed to send can never become "a time we offered". |
| `book_choice` | conversation_id, choice, actor | Turn 3's booking, with nobody approving it (a deliberate choice). |

**`app/services/email_service.py`**: Email ingestion pipeline (FR-EMAIL-01/02).

| Function | Arguments | Purpose |
|---|---|---|
| `hold_undrafted` | task, actor, reason, handover | No draft to approve, so a person answers: the reason on the message and an agent_failure item for the operator. Flushes, never commits. |
| `ingest_email` | payload, actor | Stores an inbound email on a new or continuing case and returns its routed task. |
| `answer_sentences` | answer | The answer without any sentence about booking, registering or sending details. The prompt asks for none; the model writes them anyway. |
| `answer_for_form_link` | email, actor | The answer to a question a new patient asked alongside a booking or sign-up request, to go above the registration link: (answer, None), or (None, why not) when there is nothing that may go out unread. |
| `approval_payload` | email_id, task_id, draft, delivery_error, critic_reason, hold_reason | Builds the approval payload for an email draft reply, including optional error and reason fields. |
| `auto_send_eligible` | verdict, gate_outcome, grounded, category | Whether a draft may go out with no human in the loop. |
| `reply_risk_tier` | revision_count, grounded_on_retry, is_provisional, branch | Whether a draft must reach a human whatever auto_send_eligible says. |
| `deliver_reply` | email_id, task_id, draft, actor, case_id, approval_id, automated, manual | Send a reply. The only caller of outlook_client.send_reply in the app. |
| `deliver_new_message` | to_address, subject, body, actor, case_id, action, details | Send a message that is not a reply. The only caller of outlook_client.send_mail in the app. |
| `check_reply_worthiness` | email, actor | Asks the language model whether an incoming email deserves a reply. |
| `mark_not_worthy` | task, reason | Nothing to reply to: park the task at low priority, saying why. |
| `reformulator` | actor | The agent graph's retrieval retry, on the same model the draft uses. |
| `generate_draft` | task, email, actor, feedback, reformulate, notes | Draft a reply. Returns (text, grounded). |
| `persist_draft` | task_id, draft_text, approval_id, sent | Saves a draft reply, approval link and sent flag against the given task. |
| `record_reply_dispatch` | task_id, case_id, actor, approval_id, delivery_error | After an approved reply's executor ran: record what actually happened. |
| `record_critic_escalation` | task_id, case_id, actor, reason, drafts | Every draft failed the critic: no approval, no send. The Task stays pending for a human to answer, with the critic's reason on it and in an agent_handover item for the message's owner. |
| `draft_reply` | task, email, actor, gate, confidence | Generate and gate a reply for an auto-routed email. |
| `draft_runner` | none | What the ingest paths schedule once ingest_email has committed. |
| `draft_reply_detached` | task_id, email_id, actor_id, gate, confidence | Run draft_reply in a session of its own. |

**`app/services/episode_service.py`**: Cases as episodes of care. Every Episode write is here.

| Function | Arguments | Purpose |
|---|---|---|
| `touch` | episode | Activity on the case, which is what the close nudge measures. |
| `category_label` | category | Turns a task category value into a readable label. |
| `get` | episode_id | Returns the episode with the given id or raises an error if missing. |
| `create` | patient_id, title, actor, doctor_id, contact | A new open case. The doctor defaults to the patient's own (NULL only when they have none); a named doctor also gets an assignment. |
| `suggest` | contact, candidates, actor | The model's pick among the open cases, by number. Anything else (junk, a number off the list, a failed or blocked call) falls back to the most recently active case, which candidates lists first. |
| `attach_contact` | contact, actor, category | The attach rule. Returns the case the contact is now in, or None. |
| `close` | episode, note, actor | Closes a case with a required outcome note, completing its open review items and auditing the closure. |
| `reopen` | episode, actor | Reopens a closed episode, clearing its closure details and recording an audit event. |
| `rename` | episode, title, actor | Renames a case episode after validating the title and records the change in the audit log. |
| `set_doctor` | episode, doctor_id, actor | Assigns a new doctor to an episode and audits the change from the previous doctor. |
| `item_contact` | kind, item_id | The item and the contact that says whose it is. |
| `move` | kind, item_id, target, actor, new_title, patient_id | Put a contact, appointment or consent in another case of the same patient, or a new one (target None). A contact nobody has confirmed yet (a voicemail) takes patient_id: staff saying who it is. |
| `staff_contact` | episode, reason, actor | The contact a staff booking or consent hangs off (appointments and consents need one): the case's most recent contact, else a new "staff" one. |
| `choose` | item, target, actor | Resolve a case_choice item: one of the offered cases, or a new one. |
| `timeline` | episode | Everything in the case, newest first: its contacts (each with the inbox message it opens), appointments, consents and Review Queue items. |

**`app/services/health_service.py`**: Real dependency probes for the Platform Ops console.

| Function | Arguments | Purpose |
|---|---|---|
| `check_all` | none | Checks the health of the database, object storage, language model and Outlook connection. |
| `active_session_count` | none | Distinct audit session ids seen recently. |

**`app/services/human_review_service.py`**: Reviewer queue service (FR-TASK-02 / FR-GOV-02's escalation surface).

| Function | Arguments | Purpose |
|---|---|---|
| `due_at` | item | Over SLA past this. High priority gets the shorter, editable window. |
| `list_tasks` | actor, status, task_type, limit, offset | Lists the review tasks a user may see, open items oldest first, with a total count. |
| `describe_tasks` | tasks | What the queue shows beside each task, keyed by task id: the case's reason and patient, who logged it (its intake.created audit event, which the case row itself doesn't record) and the owner's name. |
| `count_tasks_by_day` | actor, week_start | Task volume per day for the Mon-Sun week starting at week_start (UTC midnight). |
| `create_task` | actor, task_type, contact_reason, priority, assigned_to, reviewed, notes | Manually log an independent case + review task (FR-TASK-ADD). |
| `can_act` | actor, item | Admin: everything. Own role: yes, and a doctor only for items assigned to them or about their patients. The operator also works the front desk's items. |
| `is_clinical` | item | Clinical if either the category recorded at draft time (item.details, set by approval_service.create_approval_request) or the inbox task's current category is clinical. |
| `can_approve` | actor, item | can_act, except that clinical text is approved only by a doctor or the admin. |
| `item_for_approval` | approval_id | Returns the most recent human review item linked to an approval request. |
| `claim_task` | task_id, actor | Claims a pending human review task for the acting user and marks it in progress. |
| `complete_task` | task_id, actor, notes | Marks a human review task as completed with optional notes and records an audit event. |
| `reject_task` | task_id, actor, notes | Dismisses a non-draft review task, saving any notes and recording an audit event. |
| `escalate_task` | task_id, actor, notes | Escalates a review task to the next role up, updating its inbox item and audit log. |
| `reroute` | task_id, actor, category | Changes a reviewed message's category and target role, escalating or opening complaint reviews as needed. |
| `link_patient` | task_id, actor, patient_id | Links the case and closes the item. The route then re-runs the agent on the linked email (agent_graph.rerun_after_review). |
| `reassign` | task_id, actor, doctor_id | A held draft to a doctor: how the operator moves clinical text it may not approve. |
| `choose_case` | task_id, actor, episode_id | "Which case does this belong to?": one of the offered cases, or a new one. |
| `answer_case_close` | task_id, actor, close, note | "Close this case?": Close (with the outcome note) or Keep open, which asks again after case_close_nudge_days of quiet. |

**`app/services/identity_service.py`**: Who sent this message. The LLM extracts, code decides.

| Function | Arguments | Purpose |
|---|---|---|
| `extract_identity_fields` | llm, content, actor, sender_name | Unparseable or blocked output means no fields, never an error. |
| `resolve_patient` | sender, fields | Exact, normalised matching only. |
| `identify_sender` | llm, intent, case_id, sender, content, actor, sender_name, mrn | Resolve, record, and for a patient-specific MATCHED link the case. |
| `hold_for_staff` | task_id, outcome, candidates | Places a task on hold for staff identity review, recording the identity outcome and candidate matches. |
| `match_phone_dob` | phone, dob | The voicemail rule: caller ID and keypad DOB match exactly one live patient, or nobody. A name is never used: speech-to-text mangles names, and staff confirm the name on the callback anyway. |
| `find_provisional_by_phone` | phone | The voicemail twin of the email address fallback: an unknown caller who already left a voicemail from this number has a provisional record, so a second call without a keypad DOB must not create another one. |

**`app/services/inbox_service.py`**: Unified, RBAC-scoped inbox feed (both channels).

| Function | Arguments | Purpose |
|---|---|---|
| `summarize_call` | llm, transcript, actor | One inbox preview line. Through the input guardrail: a call transcript is untrusted external text, same as an email body. |
| `can_act_on_task` | actor, task | Access rule on the message itself, so it holds with no review item too: what the actor's own inbox shows (the admin sees everything), plus the front desk's messages for the operator. |
| `write_reply_open` | task | Write reply: an email nothing was sent on, with no AI draft awaiting approval. Covers no draft, a blocked one, a rejected one, and an approved one whose delivery failed. |
| `openable_task` | actor, task_id | The inbox's own message, or one a review item links the actor to (e.g. an operator opening a front desk item, or a doctor a reassigned draft). |
| `get_message` | actor, task_id | Returns an inbox message with its review details if the user may open the task. |
| `write_reply` | actor, task, text | Send a person's own reply through deliver_reply, the only send path: no approval and no critic, a person wrote it. The linked items it answers close in the same commit. The caller checks can_act_on_task. |
| `list_inbox` | actor, limit, offset, archived | Lists one page of the inbox messages the user may see, with their review state. |

**`app/services/intake_service.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `create_intake` | payload, actor | Creates a new intake case for an existing patient and records the creation event. |
| `get_case` | case_id | Returns an intake case by its identifier, or nothing if it does not exist. |
| `list_cases` | search, status, channel, patient_id, limit, offset | Lists intake cases newest first with optional search, status, channel and patient filters plus total count. |
| `update_case_status` | case_id, status, actor | Changes an intake case's status and records the change in the audit log. |

**`app/services/intent_check.py`**: A computed second opinion on the LLM classifier's category (email only).

| Function | Arguments | Purpose |
|---|---|---|
| `probabilities` | vector | Softmax over the ten categories, the same as the regression's predict_proba. |
| `regression_view` | text | The regression's category for this email and its top-1 minus top-2 margin. |

**`app/services/medication_service.py`**: Medication history, and the clinical access rule that guards it.

| Function | Arguments | Purpose |
|---|---|---|
| `get_medication_history` | patient_id, actor | Every medication on record for this patient, newest prescription first. |
| `check_last_review_date` | medications, today | Whether a review is due before anything can be renewed. |
| `prescriber_id` | medications | Who to send the internal request to: the prescriber of the most recent active medication, or None when nothing on record names one. |

**`app/services/onboarding_service.py`**: Onboarding a sender nobody can identify.

| Function | Arguments | Purpose |
|---|---|---|
| `start_onboarding` | case_id, sender, fields, actor | None when there is no name to file the record under: Patient.name is NOT NULL, and inventing one would be worse than handing this to staff. |
| `fields_to_request` | patient | Which ASKABLE fields are still missing. patient_service owns what "missing" means for the profile; dob is not a PROFILE_FIELDS column. |
| `draft_onboarding_reply` | llm, email, name, requested, actor, feedback | Drafts an onboarding email reply asking a new patient for missing registration details. |

**`app/services/outlook_auth.py`**: Microsoft Graph token acquisition for the inbound mail connector.

| Function | Arguments | Purpose |
|---|---|---|
| `connected_account` | none | The signed-in mailbox, read straight from the cache (no network). |
| `load_cache` | none | Loads the saved Outlook sign-in token cache from disk, or returns an empty cache. |
| `save_cache` | cache | Writes the Outlook token cache to disk with owner-only permissions when it has changed. |
| `build_app` | cache | Builds the Microsoft authentication client used to sign in to Outlook. |
| `start_sign_in` | redirect_uri, user_id | Starts the Microsoft sign-in flow for Outlook and returns the authorisation URL. |
| `finish_sign_in` | params | Complete a sign-in from Microsoft's redirect; returns (who started it, mailbox). |
| `get_access_token` | none | Return a valid access token, refreshing silently from the cache. |

**`app/services/outlook_client.py`**: Microsoft Graph mail client for the inbound connector.

| Function | Arguments | Purpose |
|---|---|---|
| `strip_html` | raw | Converts HTML email content to plain text by removing tags, decoding entities and collapsing whitespace. |
| `to_ingest_request` | message | Map one Graph message onto the pipeline's existing ingest contract. |
| `get_unread_emails` | access_token, top | Fetch unread inbox messages, newest first. |
| `mark_as_read` | access_token, message_id | Marks an Outlook message as read through the Microsoft Graph API. |
| `send_reply` | access_token, message_id, reply_body | Reply to a message in its own thread. |
| `send_mail` | access_token, to_address, subject, body | Send a new message, for outbound mail with nothing to reply to. |

**`app/services/outlook_poller.py`**: Background poll loop for the Outlook connector.

| Function | Arguments | Purpose |
|---|---|---|
| `get_or_create_connector_actor` | none | The service identity the poller attributes ingested mail to. |
| `poll_once` | none | Runs one Outlook mailbox sync and logs how many emails were fetched and ingested. |
| `run_poller` | none | Poll until cancelled. |

**`app/services/outlook_sync_service.py`**: Pull unread Outlook mail into the existing email pipeline.

| Function | Arguments | Purpose |
|---|---|---|
| `schedule` | fn | Run fn(*args) behind the semaphore, holding a strong reference to it, and return immediately. |
| `schedule_draft` | task_id, email_id, actor_id, gate, confidence | Queue a draft to run behind the semaphore and return immediately. |
| `sync_inbox` | actor | Fetch unread mail and run each message through the email pipeline. |

**`app/services/own_appointment_service.py`**: A patient's own upcoming appointment, by email: say when it is, or cancel it.

| Function | Arguments | Purpose |
|---|---|---|
| `patient_for_sender` | sender | The one patient whose record has this address. A shared family inbox (two records) is nobody: the email does not say which. |
| `upcoming` | patient_id | Lists a patient's future pending or confirmed appointments in time order. |
| `target` | text, appointments, moving | The appointment the email means, or None when that is not certain. |
| `describe` | appointment | "Tuesday 1 September at 8:00am with Dr Priya Menon". |
| `slot_text` | appointment, doctor_name | Formats an appointment's time slot and doctor name as readable text. |
| `when_text` | name, described | Builds the patient email listing their upcoming appointments, or saying none were found. |
| `which_text` | name, described | Writes the email asking a patient which upcoming appointment they mean. |
| `cancelled_text` | name, described | Builds the email text telling a patient their appointment has been cancelled. |
| `late_text` | name, described | Builds the reply telling a patient their late cancellation request will be confirmed by the front desk. |
| `move_staff_text` | name, described | Builds the patient email saying staff will contact them to move one of several appointments. |
| `late_reason` | appointment, doctor_name | What the front desk's Review Queue item says. |
| `confirmation_code` | conversation_id, appointment_id, action | Six digits for one request to cancel or move one appointment. |
| `confirmed_action` | written, conversation_id, appointment_id | "cancel" or "move" when what the sender wrote carries that request's code and does not read as a refusal; None otherwise. written is the new text of the reply, never the quoted email under it, which holds the code. |
| `confirm_text` | name, described, action, code | Writes the email asking a patient to confirm a cancel or change request with a code. |
| `is_late` | appointment | Checks whether an appointment is too close to its start time to change. |
| `cancel` | appointment, actor | Cancels an appointment at the patient's emailed request on the agent's behalf and records an audit event. |

**`app/services/patient_form_service.py`**: The registration form link.

| Function | Arguments | Purpose |
|---|---|---|
| `enabled` | none | Checks whether the patient registration form link feature and its prerequisite features are all enabled. |
| `token_hash` | token | Returns the SHA-256 hash of a patient form token. |
| `issue_link` | conversation | A new link for this conversation. The caller commits; the link only opens once record_sent has stamped form_sent_at. |
| `needs_preferred_day` | conversation | Checks whether the conversation began as an appointment request needing a preferred day. |
| `find_open` | token, lock | The conversation this link belongs to, if the link can still be used. lock=True takes a row lock, so two submits cannot both get through. |
| `link_text` | link, answer | answer is what the sender also asked, already checked (email_service.answer_for_form_link). |
| `task_for` | case_id | The Task of the email that opened the case. Task has no email column, and later emails on the case add Tasks of their own. |
| `submit` | conversation, payload, actor | Record a submitted form. Returns the patient it landed on, or None when staff take over: the details partly match someone else, or they contradict the record the patient's earlier email started. |
| `send_followup` | conversation_id, part_of_day | After a submitted form: the MRN and the free times, as a reply in the original thread so the patient's answer links back to the case. |

**`app/services/patient_service.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `check_preferred_doctor` | doctor_id | A preference must name an active doctor when it is recorded. One who leaves later is skipped by assignment_service.ensure_doctor. |
| `assert_not_provisional` | patient_id | Raises an error if the given patient is still provisional and needs staff to complete registration. |
| `assert_bookable` | patient, confirmed_email_id | The exception to assert_not_provisional, and its only one. |
| `fill_provisional_fields` | patient, actor | Fill the gaps in a provisional record from what the patient wrote. |
| `missing_profile_fields` | patient | Returns the names of required profile fields that are empty on a patient record. |
| `is_profile_complete` | patient | Checks whether a patient's profile has all required details filled in. |
| `create_patient` | payload, actor | Registers a new patient with a unique MRN, sets their status and assigns a doctor. |
| `update_patient` | patient, payload, actor | Applies profile edits to a patient, recalculates their status without activating provisional patients, and audits the change. |
| `create_provisional_patient` | case_id, name, email, phone, dob, actor, commit | A patient known only from an inbound message, linked to its case. PENDING and provisional until a human promotes them. |
| `promote_patient` | patient_id, actor | Provisional -> registered. Human-only (the route needs REGISTER_PATIENT), and only with explicit consent: a CAPTURED record that is not the implied consent onboarding recorded. None if there is no such patient. |
| `get_patient_by_id` | patient_id, doctor_id, include_provisional | Returns a patient by ID, optionally limited to a doctor's patients and excluding provisional records. |
| `list_patients` | search, status, sort, limit, offset, doctor_id, include_provisional | include_provisional: only for callers holding REGISTER_PATIENT, so staff can find and promote them. Takes no actor, so the route decides. |

**`app/services/permission_service.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `grant_permission` | target, permission, actor | Grants a permission to a user if their role allows it and records an audit event. |
| `revoke_permission` | target, permission, actor | Removes a granted permission from a user and records the revocation in the audit log. |

**`app/services/prescription_service.py`**: Repeat prescription requests.

| Function | Arguments | Purpose |
|---|---|---|
| `draft_prescription_reply` | name, review_due | One of two acknowledgements. No drug name, no dose, no clinical detail. |
| `request_from_doctor` | case_id, patient_id, doctor_id, actor, review_due | The internal half: a Task for the prescriber, never an email. |
| `handle_renewal` | case_id, patient_id, actor | Read the history, raise the internal request, and say which reply applies. |

**`app/services/provisional_purge.py`**: Anonymise provisional patients nobody claimed.

| Function | Arguments | Purpose |
|---|---|---|
| `purge_cancellation_text` | slots | Names nobody (the identity was never verified) and invents no phone number or link: the clinic's contact details are not a setting. |
| `purge_due` | actor | Anonymise every provisional patient past the TTL. Returns their ids. |
| `purge_once` | none | Purges provisional patients whose claim period has expired and logs how many were removed. |
| `run_purge` | none | Sweep until cancelled. One bad cycle must not kill the loop: nothing restarts it short of an app restart (same policy as the Outlook poller). |

**`app/services/records_service.py`**: Acknowledging a request for a copy of a patient's records.

| Function | Arguments | Purpose |
|---|---|---|
| `has_explicit_consent` | patient_id | Whether this PATIENT has given consent a person actually signed. |
| `draft_records_reply` | name, consent_on_file | Builds the reply to a medical records request, depending on whether consent is on file. |

**`app/services/reply_gate.py`**: Reply-worthiness gate: does an incoming email deserve a reply at all?

| Function | Arguments | Purpose |
|---|---|---|
| `evaluate_reply_worthiness` | llm, sender, subject, body, actor | Decides whether an email deserves a reply, skipping automated senders and asking the language model otherwise. |

**`app/services/reply_parsing.py`**: What the sender wrote in this message, without the history quoted under it.

| Function | Arguments | Purpose |
|---|---|---|
| `strip_quoted` | text | The new part of a reply. Top-posted: everything above the first quote header. Inline (answers between "> " lines): the text above it plus every unquoted line below it. |

**`app/services/review_backfill.py`**: Review Queue items for messages already waiting when the queue shipped.

| Function | Arguments | Purpose |
|---|---|---|
| `backfill` | actor | Open the missing items and commit. Returns how many were opened. |

**`app/services/review_routing.py`**: Review Queue items the system opens itself.

| Function | Arguments | Purpose |
|---|---|---|
| `owner_for` | inbox_task, kind | (target_role, assigned_to) for a new item. |
| `open_item` | kind, inbox_task, reason, actor, approval_id, details, priority, owner, assigned_to | The one open item for this message and kind, created if missing. |
| `close_for_approval` | approval_id, actor, approved, notes | Approve or reject, from either screen, closes the linked item. |
| `complete_open` | case_id, kind, actor, note | Close a case's open items that something else has settled (e.g. the conversation verified the sender). Flushes, never commits. |

**`app/services/routing_rules.py`**: Canonical mapping from triage category to routing action and queue.

| Function | Arguments | Purpose |
|---|---|---|
| `decide` | category | Map a triage category to (routing_action, target_queue, escalated). |

**`app/services/routing_service.py`**: Routing service , takes a triage result, applies routing rules, persists a RoutingDecision. Distinct from triage classification.

| Function | Arguments | Purpose |
|---|---|---|
| `route_from_triage_id` | triage_id, actor | Creates a routing decision from a triage result, marks it routed and logs the decision. |
| `get_decision_for_case` | case_id | Returns the latest routing decision recorded for a case. |

**`app/services/settings_service.py`**: Runtime configuration overrides on top of app/config.py.

| Function | Arguments | Purpose |
|---|---|---|
| `shown` | key | (value, default, spec) for a setting as the Settings page shows it. |
| `bedrock_model_name` | model_id | The name Bedrock gives a model id, or the id itself when Bedrock will not say. |
| `validate` | values | Validate a whole batch. Raises before anything is written. |
| `hydrate` | none | Load stored overrides onto the settings singleton. |
| `set_settings` | values, actor | Validate, persist, audit and apply a batch of settings. |

**`app/services/system_actor.py`**: Service identities for work no logged-in human initiated.

| Function | Arguments | Purpose |
|---|---|---|
| `get_or_create_system_actor` | email, full_name, role | Fetch a service account, creating it on first use. |
| `get_or_create_agent_actor` | none | The identity the agent graph attributes its actions to. |

**`app/services/task_routing_gate.py`**: Confidence gate for task routing (FR-GOV-02), reusing the existing 3-tier shape from app.rag.gating.

| Function | Arguments | Purpose |
|---|---|---|
| `evaluate_task_routing_gate` | category, confidence, text | Decide whether a classified task auto-routes, auto-routes but gets flagged for audit sampling, or goes straight to the human reviewer queue. |

**`app/services/task_routing_rules.py`**: Category -> target role resolver (FR-TRIAGE-01 / FR-GOV-02).

| Function | Arguments | Purpose |
|---|---|---|
| `resolve_target_role` | category | Map a task category to the role whose queue it lands in. |

**`app/services/task_service.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `create_task` | payload, actor | Creates a manual task on an existing case and records the creation in the audit log. |
| `get_task` | task_id | Returns a task by its identifier, or nothing if it does not exist. |
| `email_for` | task | The email this task was opened for. Tasks from before tasks.email_id (and internal ones, such as a prescriber's task) fall back to the last email on the case that was already there when the task was made. |
| `list_tasks` | none | Lists all non-deleted tasks newest first, adding each one's subject and sender name. |
| `update_task` | task_id, payload, actor | Updates a task's status, assignee or priority and records the change in the audit log. |
| `add_comment` | task_id, payload, actor | Adds a comment to a task and records the comment in the audit log. |
| `list_comments` | task_id | Lists a task's comments in the order they were created. |
| `mark_escalated` | task, actor, reason | ESCALATED + URGENT, audited, never committed. |
| `escalate_task` | task_id, reason, actor | Mark a task ESCALATED and bump it to URGENT priority. |
| `apply_gate` | task, gate, actor, reasons, in_conversation | What a HUMAN_REVIEW routing outcome opens, the same for email, logged calls and voicemail. Flushes, never commits. |
| `archive_task` | task_id, actor | Mark a task COMPLETED. Removes it from the RBAC-scoped inbox feed (inbox_service excludes COMPLETED tasks), same as archiving an email. |
| `soft_delete_task` | task_id, actor | Hide a task from both the inbox and the archived view while keeping the row and its audit trail , hard-deleting an ingested patient email would destroy the evidence it ever arrived, unacceptable in a clinical audit context. |
| `mark_task_read` | task_id, actor | Marks a task as read by the user after checking they may access it. |
| `override_task` | task_id, category, reason, actor | Overrides a task's category, re-routes it to the matching role and audits the reason. |
| `hold_for_staff` | task_id, reason, review_kind, details, owner, assigned_to | No draft: say why on the message, and put it in its owner's Review Queue. |
| `record_agent_failure` | task_id, case_id, actor, stage, error_type, error_detail | An agent graph node raised: make sure a human sees the case. |

**`app/services/transcription_service.py`**: Speech-to-text on the server for calls and voicemail (faster-whisper).

| Function | Arguments | Purpose |
|---|---|---|
| `transcribe_audio` | audio_bytes | Transcribes uploaded audio to text with the speech model, rejecting silent recordings. |
| `transcribe_audio_with_quality` | audio_bytes | For voicemail: the transcript plus how far to trust it. Silence is an empty, low-quality transcript, never an error: a silent voicemail still has a caller ID worth calling back. |

**`app/services/triage_service.py`**: Rules-based triage classifier for the manual `POST /triage` endpoint.

| Function | Arguments | Purpose |
|---|---|---|
| `matches_any` | text, keywords | Substring match , handles multi-word phrases like 'chest pain'. |
| `is_urgent` | text | True if the text names a red-flag symptom, or uses an urgency word that is not negated. Red flags are never negated away: missing an emergency costs far more than a human reading one routine email. |
| `classify` | request, actor | Triages a consented case by keyword rules into an urgency category, stores the result and audits it. |

**`app/services/twilio_client.py`**: Twilio request signatures, and downloading then deleting each voicemail recording (privacy APP 8).

| Function | Arguments | Purpose |
|---|---|---|
| `valid_signature` | path, params, signature | Checks that an incoming Twilio webhook request carries a valid signature. |
| `download_recording` | recording_sid | Downloads a Twilio call recording as WAV audio. |
| `delete_recording` | recording_sid | True when Twilio no longer holds it (404 counts: already gone). |

**`app/services/user_service.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `set_department` | target, department, actor | Updates a user's department and records the change in the audit log. |
| `list_departments` | none | Every department in use, for the directory's filter. Taken from the whole table, not from the page being returned, or a department belonging only to users further down the list is never offered. |
| `list_users` | search, limit, offset, role, department | A page of users and the total number matching the filters. |
| `set_active_status` | target, is_active, actor | Activates or deactivates a user account and records the change in the audit log. |
| `get_grants` | target | Returns the extra permissions granted to a user. |

**`app/services/voicemail_service.py`**: The voicemail channel.

| Function | Arguments | Purpose |
|---|---|---|
| `clinic_is_open` | now | Weekday, inside clinic hours, not a public holiday, all in clinic time. |
| `is_withheld` | from_number | Checks whether a caller's number is withheld or not a valid phone number. |
| `parse_keypad_dob` | digits, today | DDMMYYYY from the keypad. Anything else is 'no DOB', never an error. |
| `audio_suffix` | filename | Returns the lower-case audio file extension if it is a supported audio type. |
| `audio_media_type` | key | Returns the audio media type for a stored voicemail file based on its file extension. |
| `intake_actor` | none | Returns the system user that voicemail intake acts as, creating it if needed. |
| `get_by_sid` | call_sid | Returns the call record matching a Twilio call SID. |
| `create_voicemail` | from_number, actor, call_sid, status, keypad_dob, keypad_intent, urgent_pressed | A new case and Call row. Idempotent on call_sid (Twilio retries). |
| `store_audio` | call, data, suffix | Saves voicemail audio to object storage and links the storage key to the call. |
| `urgent_script` | call, reasons | Builds the urgent voicemail alert text, telling staff to call back or to listen for a number. |
| `ensure_task` | call | The call's one Task, created before any slow step so a failure lands on a Task that links to the call (and its audio). A caller who pressed 9 is URGENT from this moment: no later failure can lose that. |
| `process` | call_id | Background entry point: its own session, never raises (nobody is left to raise to). Idempotent: only a `received` call is processed. |
| `callback_script` | call, state | The callback task's text. A template: no model decides what staff are told to offer. |
| `handle_call_ended` | call, actor | The call ended with no recording coming. Pressed 9 first: an URGENT callback task. Otherwise nothing to act on. |

**`app/services/voicemail_sweep.py`**: The voicemail sweep: deletes old audio, closes calls with no end-of-call callback, and reprocesses voicemails a restart left behind.

| Function | Arguments | Purpose |
|---|---|---|
| `sweep_once` | now | Runs one voicemail clean-up pass, purging expired audio and deleting recordings held by Twilio. |
| `run_voicemail_sweep` | none | Runs the voicemail sweep in a background loop at the configured interval. |


## 3. Routes (handlers)

**`app/routes/appointments.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `book_appointment_endpoint` | payload, actor | Handler for POST `/` under the router prefix (Appendix D). |
| `list_appointments_endpoint` | doctor_id, patient_id, date_from, date_to, appointment_type, status_filter, search, limit, offset, actor | Handler for GET `/` under the router prefix (Appendix D). |
| `get_calendar_endpoint` | year, month, doctor_id, actor | Handler for GET `/calendar` under the router prefix (Appendix D). |
| `get_calendar_markers_endpoint` | year, month, doctor_id, actor | Handler for GET `/calendar/markers` under the router prefix (Appendix D). |
| `get_day_endpoint` | day, doctor_id, actor | Handler for GET `/day` under the router prefix (Appendix D). |
| `get_availability_endpoint` | doctor_id, day, slot_minutes, actor | Handler for GET `/availability` under the router prefix (Appendix D). |
| `suggest_appointments_endpoint` | payload, actor | Handler for POST `/suggest` under the router prefix (Appendix D). |
| `get_appointment_endpoint` | appointment_id, actor | Handler for GET `/{appointment_id}` under the router prefix (Appendix D). |
| `update_appointment_endpoint` | appointment_id, payload, actor | Handler for PATCH `/{appointment_id}` under the router prefix (Appendix D). |
| `complete_appointment_endpoint` | appointment_id, actor | Handler for POST `/{appointment_id}/complete` under the router prefix (Appendix D). |
| `reschedule_appointment_endpoint` | appointment_id, payload, actor | Handler for POST `/{appointment_id}/reschedule` under the router prefix (Appendix D). |
| `cancel_appointment_endpoint` | appointment_id, actor, payload | Handler for POST `/{appointment_id}/cancel` under the router prefix (Appendix D). |

**`app/routes/approvals.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `list_approvals_endpoint` | status_filter, action_type, case_id, limit, offset, _ | Handler for GET `/` under the router prefix (Appendix D). |
| `approve_endpoint` | approval_id, payload, background_tasks, actor | Handler for POST `/{approval_id}/approve` under the router prefix (Appendix D). |
| `reject_endpoint` | approval_id, payload, background_tasks, actor | Handler for POST `/{approval_id}/reject` under the router prefix (Appendix D). |

**`app/routes/assignments.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `create_assignment_endpoint` | payload, actor | Handler for POST `/` under the router prefix (Appendix D). |
| `delete_assignment_endpoint` | doctor_id, patient_id, actor | Handler for DELETE `/{doctor_id}/{patient_id}` under the router prefix (Appendix D). |
| `list_assignments_endpoint` | doctor_id, _ | Handler for GET `/` under the router prefix (Appendix D). |

**`app/routes/audit.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `list_audit_events` | actor_id, action, risk_level, outcome, case_id, from_time, to_time, limit, offset, format, actor | Handler for GET `/` under the router prefix (Appendix D). |
| `verify_audit_chain_route` | actor | Handler for GET `/verify` under the router prefix (Appendix D). |
| `list_incidents_endpoint` | limit, _ | Governance blocks, newest first, for the Platform Ops incident feed. |
| `get_audit_for_case` | case_id, actor | Handler for GET `/by-case/{case_id}` under the router prefix (Appendix D). |
| `get_audit_event` | event_id, actor | Handler for GET `/{event_id}` under the router prefix (Appendix D). |

**`app/routes/auth.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `register` | payload, actor | Create a front_desk account. Admin only: the Users page is the one caller, and on a public URL an open door would let anyone in. The first admin on a fresh installation comes from scripts/create_admin.py. |
| `elevate_user_role` | user_id, payload, actor | Change a user's role. Admin only. |
| `set_department_endpoint` | user_id, payload, actor | Set a user's department. Admin only. |
| `set_active_status_endpoint` | user_id, payload, actor | Activate or deactivate a user. Admin only. |
| `get_user_grants_endpoint` | user_id, actor | List a user's real per-user permission grants. Admin only. |
| `list_users_endpoint` | search, role, department, limit, offset, _ | Handler for GET `/users` under the router prefix (Appendix D). |
| `grant_permission_endpoint` | user_id, payload, actor | Handler for POST `/users/{user_id}/grants` under the router prefix (Appendix D). |
| `revoke_permission_endpoint` | user_id, permission, actor | Handler for DELETE `/users/{user_id}/grants/{permission}` under the router prefix (Appendix D). |
| `login` | request, form_data | Handler for POST `/login` under the router prefix (Appendix D). |
| `me` | current_user | Handler for GET `/me` under the router prefix (Appendix D). |
| `change_own_password` | payload, current_user | Change the signed-in user's own password. |
| `request_password_reset` | request, payload, background | Email a reset link if the account exists. |
| `confirm_password_reset` | request, payload | Handler for POST `/password-reset/confirm` under the router prefix (Appendix D). |

**`app/routes/calls.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `create_call_endpoint` | payload, actor | Handler for POST `/` under the router prefix (Appendix D). |
| `list_calls_endpoint` | _ | Handler for GET `/` under the router prefix (Appendix D). |
| `route_call_endpoint` | call_id, payload, actor | Handler for POST `/{call_id}/route` under the router prefix (Appendix D). |
| `override_call_routing_endpoint` | call_id, payload, actor | Handler for POST `/{call_id}/override-routing` under the router prefix (Appendix D). |
| `escalate_call_endpoint` | call_id, payload, actor | Handler for POST `/{call_id}/escalate` under the router prefix (Appendix D). |
| `transcribe_call_endpoint` | audio, _ | Handler for POST `/transcribe` under the router prefix (Appendix D). |
| `call_audio_endpoint` | call_id, actor | Handler for GET `/{call_id}/audio` under the router prefix (Appendix D). |
| `get_call_endpoint` | call_id, _ | Handler for GET `/{call_id}` under the router prefix (Appendix D). |

**`app/routes/clinical_documents.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `list_clinical_documents_endpoint` | patient_id, actor | Handler for GET `/` under the router prefix (Appendix D). |
| `upload_clinical_document_endpoint` | patient_id, doc_type, file, actor | Handler for POST `/` under the router prefix (Appendix D). |
| `ingest_clinical_document_endpoint` | document_id, actor | Handler for POST `/{document_id}/ingest` under the router prefix (Appendix D). |
| `download_clinical_document_endpoint` | document_id, actor | Handler for GET `/{document_id}/file` under the router prefix (Appendix D). |

**`app/routes/consent.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `create_consent_endpoint` | payload, actor | Handler for POST `/` under the router prefix (Appendix D). |
| `list_consents_for_patient_endpoint` | patient_id, actor | Handler for GET `/` under the router prefix (Appendix D). |
| `consent_queue_endpoint` | limit, offset, _ | The staff consent queue: real records, not the recent cases. |
| `get_consent_by_case_endpoint` | case_id, consent_id, actor | Handler for GET `/by-case/{case_id}` under the router prefix (Appendix D). |
| `capture_consent_endpoint` | consent_id, payload, actor | Handler for POST `/{consent_id}/capture` under the router prefix (Appendix D). |
| `verify_consent_endpoint` | consent_id, payload, actor | Staff checked ID for a patient who registered online, and finished anything the patient left for the clinic. |
| `resolve_review_endpoint` | consent_id, payload, actor | Handler for POST `/{consent_id}/resolve-review` under the router prefix (Appendix D). |
| `withdraw_consent_endpoint` | consent_id, actor | Handler for POST `/{consent_id}/withdraw` under the router prefix (Appendix D). |

**`app/routes/doctors.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `list_doctors_endpoint` | search, actor | Handler for GET `/` under the router prefix (Appendix D). |

**`app/routes/email.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `ingest_email_endpoint` | payload, background_tasks, actor | Handler for POST `/ingest` under the router prefix (Appendix D). |

**`app/routes/episodes.py`**: Cases (episodes of care).

| Function | Arguments | Purpose |
|---|---|---|
| `list_cases_endpoint` | patient_id, status_filter, limit, offset, actor | Handler for GET `/` under the router prefix (Appendix D). |
| `create_case_endpoint` | payload, actor | Handler for POST `/` under the router prefix (Appendix D). |
| `get_case_endpoint` | episode_id, actor | Handler for GET `/{episode_id}` under the router prefix (Appendix D). |
| `update_case_endpoint` | episode_id, payload, actor | Handler for PATCH `/{episode_id}` under the router prefix (Appendix D). |
| `close_case_endpoint` | episode_id, payload, actor | Handler for POST `/{episode_id}/close` under the router prefix (Appendix D). |
| `reopen_case_endpoint` | episode_id, actor | Handler for POST `/{episode_id}/reopen` under the router prefix (Appendix D). |
| `staff_contact_endpoint` | episode_id, payload, actor | The contact a staff booking or consent for this case files under. |
| `move_endpoint` | payload, actor | Put a contact, appointment or consent in another case of the same patient, or a new one; for an unconfirmed contact, confirm the patient too. |

**`app/routes/health.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `health_check` | none | Handler for GET `/health` under the router prefix (Appendix D). |
| `detailed_health` | _ | Handler for GET `/detailed` under the router prefix (Appendix D). |

**`app/routes/human_review.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `list_tasks_endpoint` | status_filter, task_type, limit, offset, actor | Handler for GET `/` under the router prefix (Appendix D). |
| `get_workflow_daily_stats_endpoint` | actor | Handler for GET `/stats/daily` under the router prefix (Appendix D). |
| `create_task_endpoint` | payload, actor | Handler for POST `/` under the router prefix (Appendix D). |
| `claim_task_endpoint` | task_id, actor | Handler for POST `/{task_id}/claim` under the router prefix (Appendix D). |
| `complete_task_endpoint` | task_id, payload, background_tasks, actor | Handler for POST `/{task_id}/complete` under the router prefix (Appendix D). |
| `reject_task_endpoint` | task_id, payload, actor | Handler for POST `/{task_id}/reject` under the router prefix (Appendix D). |
| `escalate_task_endpoint` | task_id, payload, actor | Handler for POST `/{task_id}/escalate` under the router prefix (Appendix D). |
| `reroute_endpoint` | task_id, payload, background_tasks, actor | Handler for POST `/{task_id}/reroute` under the router prefix (Appendix D). |
| `link_patient_endpoint` | task_id, payload, background_tasks, actor | Handler for POST `/{task_id}/link-patient` under the router prefix (Appendix D). |
| `reassign_endpoint` | task_id, payload, actor | Handler for POST `/{task_id}/reassign` under the router prefix (Appendix D). |
| `choose_case_endpoint` | task_id, payload, actor | Handler for POST `/{task_id}/choose-case` under the router prefix (Appendix D). |
| `case_close_endpoint` | task_id, payload, actor | Handler for POST `/{task_id}/case-close` under the router prefix (Appendix D). |

**`app/routes/inbox.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `list_inbox_endpoint` | limit, offset, archived, actor | Handler for GET `/` under the router prefix (Appendix D). |
| `get_inbox_message_endpoint` | task_id, actor | One message: the inbox's own, or one a review item links the actor to. |
| `write_reply_endpoint` | task_id, payload, actor | Write reply: a person's own answer, sent as written. |

**`app/routes/intake.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `create_intake_endpoint` | payload, actor | Handler for POST `/` under the router prefix (Appendix D). |
| `list_intake_endpoint` | search, status, channel, patient_id, limit, offset, _ | Handler for GET `/` under the router prefix (Appendix D). |
| `get_intake_endpoint` | case_id, _ | Handler for GET `/{case_id}` under the router prefix (Appendix D). |
| `update_intake_status_endpoint` | case_id, payload, actor | Handler for PATCH `/{case_id}/status` under the router prefix (Appendix D). |

**`app/routes/integrations.py`**: Clinic mailbox status and "Sign in with Microsoft" from Settings, Integrations.

| Function | Arguments | Purpose |
|---|---|---|
| `mailbox_status` | _ | Handler for GET `/` under the router prefix (Appendix D). |
| `start_sign_in` | request, actor | Handler for POST `/connect` under the router prefix (Appendix D). |
| `finish_sign_in` | request | Microsoft redirects the browser here, so there is no bearer token: the single-use OAuth state issued by /connect is what ties it to an admin. |

**`app/routes/llm.py`**: LLM diagnostic endpoints.

| Function | Arguments | Purpose |
|---|---|---|
| `llm_status` | _ | Report which LLM provider is currently configured. |
| `llm_ping` | payload, actor | Send a prompt to the configured LLM and return its response. |

**`app/routes/patients.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `create_patient_endpoint` | payload, actor | Handler for POST `/` under the router prefix (Appendix D). |
| `list_patients_endpoint` | search, status, sort, limit, offset, actor | Handler for GET `/` under the router prefix (Appendix D). |
| `get_patient_endpoint` | patient_id, actor | Handler for GET `/{patient_id}` under the router prefix (Appendix D). |
| `update_patient_endpoint` | patient_id, payload, actor | Handler for PATCH `/{patient_id}` under the router prefix (Appendix D). |
| `promote_patient_endpoint` | patient_id, actor | Provisional -> registered. Human-only, and only once explicit consent has been captured through the ordinary consent flow. |
| `change_patient_doctor_endpoint` | patient_id, payload, actor | Who the patient's doctor is. ASSIGN_PATIENTS, the permission that already governs which doctor may see a patient. |

**`app/routes/public_registration.py`**: The registration form's two public endpoints (patient_form_service).

| Function | Arguments | Purpose |
|---|---|---|
| `open_registration_link` | request, token | Handler for GET `/{token}` under the router prefix (Appendix D). |
| `submit_registration` | request, token, payload, background | Handler for POST `/{token}` under the router prefix (Appendix D). |

**`app/routes/rag.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `list_indexed_documents_endpoint` | patient_id, actor | Handler for GET `/documents` under the router prefix (Appendix D). |
| `rag_query_endpoint` | payload, actor | Handler for POST `/query` under the router prefix (Appendix D). |

**`app/routes/routing.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `route_endpoint` | payload, actor | Handler for POST `/` under the router prefix (Appendix D). |
| `get_routing_endpoint` | case_id, _ | Handler for GET `/by-case/{case_id}` under the router prefix (Appendix D). |

**`app/routes/settings.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `list_settings_endpoint` | _ | Handler for GET `/` under the router prefix (Appendix D). |
| `update_settings_endpoint` | payload, actor | Handler for PATCH `/` under the router prefix (Appendix D). |

**`app/routes/tasks.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `create_task_endpoint` | payload, actor | Handler for POST `/` under the router prefix (Appendix D). |
| `list_tasks_endpoint` | _ | Handler for GET `/` under the router prefix (Appendix D). |
| `get_task_endpoint` | task_id, _ | Handler for GET `/{task_id}` under the router prefix (Appendix D). |
| `update_task_endpoint` | task_id, payload, actor | Handler for PATCH `/{task_id}` under the router prefix (Appendix D). |
| `list_comments_endpoint` | task_id, _ | Handler for GET `/{task_id}/comments` under the router prefix (Appendix D). |
| `add_comment_endpoint` | task_id, payload, actor | Handler for POST `/{task_id}/comments` under the router prefix (Appendix D). |
| `override_task_endpoint` | task_id, payload, actor | Handler for POST `/{task_id}/override` under the router prefix (Appendix D). |
| `escalate_task_endpoint` | task_id, payload, actor | Handler for POST `/{task_id}/escalate` under the router prefix (Appendix D). |
| `archive_task_endpoint` | task_id, actor | Handler for POST `/{task_id}/archive` under the router prefix (Appendix D). |
| `delete_task_endpoint` | task_id, actor | Handler for DELETE `/{task_id}` under the router prefix (Appendix D). |
| `mark_task_read_endpoint` | task_id, actor | Handler for POST `/{task_id}/read` under the router prefix (Appendix D). |

**`app/routes/triage.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `triage_endpoint` | request, actor | Handler for POST `/` under the router prefix (Appendix D). |

**`app/routes/voice.py`**: Twilio voicemail webhooks.

| Function | Arguments | Purpose |
|---|---|---|
| `twilio_form` | request | Reads a Twilio webhook form and rejects requests with an invalid signature or account. |
| `incoming` | form | Handler for POST `/incoming` under the router prefix (Appendix D). |
| `gather` | step, form | Handler for POST `/gather/{step}` under the router prefix (Appendix D). |
| `done` | form | Handler for POST `/done` under the router prefix (Appendix D). |
| `recording` | background_tasks, form | Handler for POST `/recording` under the router prefix (Appendix D). |
| `call_status` | form | Handler for POST `/status` under the router prefix (Appendix D). |

**`app/routes/voicemails.py`**: Test voicemail intake from an uploaded audio file, used for demos and tests.

| Function | Arguments | Purpose |
|---|---|---|
| `simulate_voicemail_endpoint` | background_tasks, audio, from_number, dob_digits, intent_digit, urgent, actor | Handler for POST `/simulate` under the router prefix (Appendix D). |


## 4. Auth

**`app/auth/dependencies.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `get_current_user` | token | Resolves the signed-in user from a bearer token, rejecting invalid tokens and inactive accounts. |
| `require_roles` | none | Dependency factory: returns a dep that 403s if the current user's role is not in the allowed set. Denials are logged to the audit trail; grants are not (see require_permission() below for the rationale). |
| `require_permission` | permission | Dependency factory: 403s if `permission` isn't in the caller's effective set. |
| `require_any_permission` | none | Dependency factory: 403s unless at least one of `permissions` is held. |

**`app/auth/permissions.py`**: Permission model for VitalAI RBAC.

| Function | Arguments | Purpose |
|---|---|---|
| `effective_permissions` | user | Returns a user's permissions from their role plus any extra grants their role allows. |

**`app/auth/rbac_registry.py`**: Introspects the FastAPI app's actual dependency graph to answer, for any registered route, what RBAC check (if any) gates it. Single source of truth for tests/test_rbac_enforcement.py; never re-derive this by hand.

| Function | Arguments | Purpose |
|---|---|---|
| `get_rbac_registry` | app | One entry per (method, full path) for every route this app actually serves, with the RBAC check (if any) FastAPI will run before the handler. |

**`app/auth/scoping.py`**: Row-level scoping helpers.

| Function | Arguments | Purpose |
|---|---|---|
| `is_assigned` | doctor_id, patient_id | Checks whether a patient is assigned to a given doctor. |
| `can_read_clinical` | user, patient_id | Checks whether a user may read a patient's clinical records, limiting doctors to assigned patients. |
| `can_list_clinical` | user, patient_id | Checks whether a user may list a patient's clinical documents, requiring doctors to be assigned. |
| `allowed_scopes` | user | Returns the document access scopes a user may read, adding restricted for clinical viewers. |
| `assigned_patient_ids_subquery` | doctor_id | Builds a query selecting the IDs of patients assigned to a doctor. |

**`app/auth/security.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `hash_password` | password | Hashes a password with bcrypt using a freshly generated salt. |
| `verify_password` | plain, hashed | Checks a plain password against its stored bcrypt hash, returning false on malformed input. |
| `create_access_token` | user_id, role | Creates a signed JWT access token carrying the user ID, role, session ID and expiry. |
| `decode_access_token` | token | Decodes and verifies a JWT access token, returning nothing if it is invalid. |
| `create_password_reset_token` | user_id, hashed_password | Creates a signed, time-limited password reset token tied to the user's current password. |
| `read_password_reset_token` | token | User id the token was issued for, or None if it is invalid or expired. |
| `reset_token_matches` | token, hashed_password | Checks that a password reset token is valid and was issued for the user's current password. |


## 5. LLM

**`app/llm/guardrail.py`**: Deterministic input guardrail: the one choke point every live LLM call site must go through instead of calling llm.ainvoke(prompt) directly.

| Function | Arguments | Purpose |
|---|---|---|
| `guarded_invoke` | llm, prompt, actor, route | The one choke point every live LLM call site must go through. |

**`app/llm/output_guardrail.py`**: Output-side restricted-terms guardrail (FR-GOV-03).

| Function | Arguments | Purpose |
|---|---|---|
| `restricted_term` | text | The first restricted term in text, or None. No audit event: for a caller deciding whether to use a piece of text at all. |
| `check_output` | text, actor, case_id | Raise OutputBlockedError if text contains a restricted term. |

**`app/llm/provider.py`**: LLM provider abstraction. Every part of the codebase that needs an LLM calls `get_llm()`.

| Function | Arguments | Purpose |
|---|---|---|
| `get_llm` | none | Returns the configured language model client, Ollama or AWS Bedrock, cached after the first call. |


## 6. RAG

**`app/rag/answer.py`**: Grounded answer synthesis over the FR-RAG-02/03 gate outcome.

| Function | Arguments | Purpose |
|---|---|---|
| `revision_block` | feedback | Prompt text asking the model to fix a rejected draft; empty when there is none. Shared with email_service's reply generator. Goes into prompts only, never into a retrieval query. |
| `answer_question` | question, ctx, actor, feedback, reformulate | feedback: a reviewer's reason for rejecting a previous answer. |

**`app/rag/chunking.py`**: Plain-Python character-based chunking for the clinical upload path.

| Function | Arguments | Purpose |
|---|---|---|
| `chunk_text` | text, chunk_size | Splits text into fixed-size chunks for embedding. |

**`app/rag/doc_scopes.py`**: doc_type -> access_scope, the one mapping both ingest paths read.

| Function | Arguments | Purpose |
|---|---|---|
| `access_scope_for_doc_type` | doc_type | Returns the access scope for a document type, defaulting to restricted. |

**`app/rag/embeddings.py`**: Embedding provider abstraction.

| Function | Arguments | Purpose |
|---|---|---|
| `get_embedding_provider` | none | One provider per process, so its SentenceTransformer loads once. |

**`app/rag/gating.py`**: Deterministic post-retrieval gate (FR-RAG-02 sufficiency).

| Function | Arguments | Purpose |
|---|---|---|
| `evaluate_retrieval` | chunks | Decides whether retrieved chunks are sufficient to proceed or need manual handling. |

**`app/rag/retrieval.py`**: Provenance-tagged chunk retrieval (FR-RAG-01), vector + Postgres full-text hybrid by default.

| Function | Arguments | Purpose |
|---|---|---|
| `list_indexed_documents` | ctx | The documents this actor can actually get answers out of for this patient. |
| `retrieve` | query, ctx, k, doc_type, strategy | Embed `query` and return the top-k chunks visible to `ctx`. |

**`app/rag/retry.py`**: Retrieval retry: one reformulated second attempt, graph only.

| Function | Arguments | Purpose |
|---|---|---|
| `retrieve_gated` | query, ctx, reformulate | retrieve() then the sufficiency gate; with a Reformulator, one retry on a rewritten query when the first attempt misses the floor. |

**`app/rag/text_extraction.py`**: PDF text extraction for clinical document uploads.

| Function | Arguments | Purpose |
|---|---|---|
| `extract_pdf_text` | pdf_bytes | Extract and clean the text layer from a PDF's pages. |


## 7. Storage

**`app/storage/object_storage.py`**: Thin MinIO (S3-compatible) wrapper for clinical document bytes.

| Function | Arguments | Purpose |
|---|---|---|
| `put_object` | key, data, content_type | Uploads a file to the object storage bucket, creating the bucket if needed. |
| `get_object` | key | Downloads an object's bytes from the configured object storage bucket. |
| `delete_object` | key | Deletes an object from the configured storage bucket by its key. |


## 8. Core

**`app/audit_context.py`**: Request-scoped context for audit enrichment (IP address, session id).

| Function | Arguments | Purpose |
|---|---|---|
| `get_ip_address` | none | Returns the client IP address stored for the current request context. |
| `get_session_id` | none | Returns the audit session ID for the current request context, if set. |
| `set_audit_context` | ip_address, session_id | Stores the request's IP address and session ID for audit logging. |
| `reset_audit_context` | ip_token, session_token | Resets the request's IP address and session id audit context variables. |

**`app/database.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `get_db` | none | Provides a database session per request, rolling back on errors and always closing it. |

**`app/main.py`**

| Function | Arguments | Purpose |
|---|---|---|
| `lifespan` | application | Handles application startup, checking data-safety settings, loading runtime settings and backfilling the review queue. |
| `request_id_middleware` | request, call_next | Middleware that tags each HTTP request with a unique ID and logs it. |
| `audit_context_middleware` | request, call_next | Middleware that captures each request's client IP and session id for audit logging. |
| `latency_middleware` | request, call_next | Middleware that measures each HTTP request's handling time and records it for monitoring. |
| `root` | none | Endpoint that returns the service name, version and links to the docs and health check. |

**`app/observability.py`**: In-process request metrics for the Platform Ops dashboard.

| Function | Arguments | Purpose |
|---|---|---|
| `mark_started` | none | Records the moment the application started, for uptime reporting. |
| `uptime_seconds` | none | Returns how many seconds the application has been running, or nothing if not started. |
| `record_latency` | ms | Records one request latency measurement in milliseconds. |
| `latency_snapshot` | none | Returns the count, average and 95th percentile of recent request latencies in milliseconds. |
| `reset` | none | Test helper. Never call from application code. |


## 9. Scripts

**`scripts/assign_missing_doctors.py`**: Give every registered patient without an active doctor one.

| Function | Arguments | Purpose |
|---|---|---|
| `documented_doctors` | none | Patient id -> the "Assigned doctor" named on that patient's corpus registration form. Empty where there is no corpus. |
| `run` | actor, apply | (patient id, doctor id) for every doctorless registered patient: the doctor planned (dry run) or assigned (apply). A second apply finds none. |
| `main` | none | Command-line script that assigns a doctor to patients without one, with a dry-run mode. |

**`scripts/create_admin.py`**: Make the first admin account, or make an existing account an admin.

| Function | Arguments | Purpose |
|---|---|---|
| `run` | email, full_name, password | Create an admin, or make the account with this email an active admin. |
| `main` | none | Command-line entry point that creates or promotes a user to administrator. |

**`scripts/ingest_appointment_history.py`**: Turn each corpus patient's appointment_history.txt into appointment rows.

| Function | Arguments | Purpose |
|---|---|---|
| `parse_history` | text | Extract visit lines. Malformed lines are skipped, never raised on: one bad line in one patient's file must not abort a 100-patient ingest. |
| `clinic_roster` | none | Doctor name -> special interest, from the Practitioners table. |
| `apply_roster` | none | Every doctor on the roster has an account and their special interest. |
| `visit_slot` | visit_date, earlier_that_day | When a corpus visit is filed: 09:00 at the clinic on the visit's own date, half an hour later for each visit that doctor already has that day. The corpus gives a date and no time. Returned as a UTC instant. |
| `doctor_user_id` | name | The doctor account for this name, created on first sight. |
| `ingest` | none | Imports historical appointments from the patient corpus into the database, staggering same-day visits per doctor. |

**`scripts/ingest_corpus.py`**: Ingester: loader/cleaner/chunker into the real chunks table.

| Function | Arguments | Purpose |
|---|---|---|
| `ingest_file` | file_path, provider, doc_type | Run the loader/cleaner/chunker unchanged, then embed and insert for real. |
| `ingest_patient` | patient_dir | Delete any existing chunks for this patient and re-insert fresh. Idempotent. |
| `main` | none | Ingests every synthetic patient folder into retrieval chunks, reporting counts and failures. |

**`scripts/ingest_corpus_documents.py`**: Ingest the synthetic corpus as real clinical documents, not bare chunks.

| Function | Arguments | Purpose |
|---|---|---|
| `render_pdf` | text | A born-digital PDF whose text layer extracts back to `text`. |
| `patient_uuid` | folder_name | Extracts the patient UUID from a corpus folder name. |
| `manifest_documents` | patient_dir | (file path, doc_type) for every document the generator recorded. |
| `ingest_patient` | patient_dir, actor | Replaces a demo patient's documents by rendering, uploading and ingesting each one from the corpus. |
| `system_actor` | none | Uploads and ingests are audited, so they need a real actor row. |
| `main` | none | Command-line script that ingests corpus documents for selected patient folders and reports any failures. |

**`scripts/ingest_org_profile.py`**: Ingester for the org-wide (non-patient) demo corpus at "Organization Profile Review/" (clinic identity, policies/FAQ, routing rules, staff directory, data classification, guardrails).

| Function | Arguments | Purpose |
|---|---|---|
| `ingest_org_profile` | none | Delete any existing org-wide chunks and re-insert fresh. Idempotent. |
| `main` | none | Ingests the clinic organisation profile documents into retrieval chunks and prints the total. |

**`scripts/outlook_login.py`**: One-time interactive Outlook login for the inbound mail connector.

| Function | Arguments | Purpose |
|---|---|---|
| `main` | none | Command-line script that signs the clinic into Outlook using the device code flow. |

**`scripts/seed_demo_appointments.py`**: Seed a month of demo appointments over the existing demo patients.

| Function | Arguments | Purpose |
|---|---|---|
| `build_demo_appointments` | patients_by_doctor, month_start | Plan one month of appointments. Pure: no DB, no randomness, no clock. |
| `seed` | none | Seeds demo appointments for the current clinic month across doctors and their assigned patients. |

**`scripts/seed_demo_patients.py`**: Backfill `patients` rows for the Synth_Dataset corpus.

| Function | Arguments | Purpose |
|---|---|---|
| `main` | none | Seeds demo patients from corpus registration forms, skipping existing ones, then grants the agent clinical access. |

**`scripts/seed_synthetic_chunks.py`**: Seed the baseline `chunks` table with the FR-RAG-01 synthetic corpus.

| Function | Arguments | Purpose |
|---|---|---|
| `seed` | none | Delete any existing synthetic chunks and re-insert the corpus fresh. |
| `main` | none | Seeds the database with synthetic document chunks and prints how many were added. |


565 public functions are listed. Private helpers (leading underscore) are documented inline in the code.

Frontend modules: each page in `src/pages/` is described in Appendix H; each adapter in `src/api/` maps one backend area (Section 7.3); `lib/apiClient.ts` is the HTTP client; `lib/auth.tsx` the session context; `lib/roles.ts` role labels and `hasPermission`; `lib/format.ts` date formatting in the clinic's time zone; `components/calendarHelpers.ts` clinic-time calendar maths.

