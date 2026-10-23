# VitalAI backend test inventory

Collected tests per file (2,188 tests in 136 files; all passed in CI run `39944661796`).

| Test file | Level | Collected tests |
|---|---|---|
| `test_agent_approval_interrupt.py` | Agent graph | 11 |
| `test_agent_booking_records.py` | Agent graph | 26 |
| `test_agent_critic.py` | Agent graph | 14 |
| `test_agent_email_graph.py` | Agent graph | 48 |
| `test_agent_graph_core.py` | Agent graph | 8 |
| `test_agent_identity.py` | Agent graph | 51 |
| `test_agent_onboarding.py` | Agent graph | 20 |
| `test_agent_prescription.py` | Agent graph | 14 |
| `test_agent_retrieval_retry.py` | Agent graph | 11 |
| `test_alembic_logging.py` | Database-only | 1 |
| `test_app_setting_model.py` | Unit and service | 1 |
| `test_appointment_calendar.py` | Database-only | 27 |
| `test_appointment_overlap.py` | Database-only | 8 |
| `test_appointment_reminders.py` | Unit and service | 25 |
| `test_appointment_scoping.py` | Security and RBAC | 8 |
| `test_appointment_service.py` | Database-only | 27 |
| `test_appointment_suggestion.py` | API | 4 |
| `test_appointments.py` | Database-only | 20 |
| `test_approval_service.py` | Unit and service | 15 |
| `test_approvals.py` | API | 17 |
| `test_assignment_service.py` | Unit and service | 8 |
| `test_assignments.py` | API | 9 |
| `test_audit.py` | API | 4 |
| `test_audit_context.py` | Unit and service | 3 |
| `test_audit_detail.py` | API | 4 |
| `test_audit_hash_chain.py` | Database-only | 6 |
| `test_audit_incidents.py` | API | 3 |
| `test_audit_list.py` | API | 6 |
| `test_audit_on_deny_failsafe.py` | Security and RBAC | 3 |
| `test_audit_service_enrichment.py` | Unit and service | 17 |
| `test_audit_trigger.py` | Database-only | 3 |
| `test_audit_verify.py` | API | 3 |
| `test_auth.py` | Security and RBAC | 27 |
| `test_auth_dependencies_rbac.py` | Security and RBAC | 7 |
| `test_calls.py` | API | 15 |
| `test_case_doctor_routing.py` | Unit and service | 4 |
| `test_case_nudge.py` | API | 17 |
| `test_chunking.py` | Unit and service | 3 |
| `test_clinic_timezone.py` | API | 10 |
| `test_clinical_document_model.py` | Unit and service | 1 |
| `test_clinical_document_service.py` | Database-only | 10 |
| `test_clinical_documents.py` | Database-only | 20 |
| `test_consent.py` | API | 22 |
| `test_consent_verify.py` | API | 10 |
| `test_content_classifier.py` | Unit and service | 15 |
| `test_corpus_pdf_ingest.py` | Unit and service | 5 |
| `test_create_admin.py` | Unit and service | 4 |
| `test_deliver_reply.py` | Unit and service | 8 |
| `test_deploy_script.py` | Unit and service | 15 |
| `test_doctor_assignment.py` | API | 14 |
| `test_doctor_suggestion.py` | Unit and service | 3 |
| `test_doctors.py` | API | 4 |
| `test_draft_reply_detached.py` | API | 6 |
| `test_email_conversation.py` | API | 92 |
| `test_email_model.py` | Unit and service | 1 |
| `test_email_routes.py` | API | 5 |
| `test_email_service.py` | Unit and service | 37 |
| `test_env_prod_example.py` | Unit and service | 4 |
| `test_episode_attach_paths.py` | API | 14 |
| `test_episode_model.py` | Unit and service | 3 |
| `test_episode_routes.py` | API | 13 |
| `test_episode_service.py` | Unit and service | 39 |
| `test_health.py` | API | 2 |
| `test_health_detailed.py` | API | 10 |
| `test_human_review_create.py` | API | 9 |
| `test_human_review_routes.py` | API | 19 |
| `test_human_review_service.py` | Unit and service | 29 |
| `test_inbox.py` | API | 15 |
| `test_ingest_appointment_history.py` | Unit and service | 9 |
| `test_intake.py` | API | 20 |
| `test_llm.py` | API | 15 |
| `test_llm_guardrail.py` | Security and RBAC | 20 |
| `test_llm_safety_net.py` | Security and RBAC | 4 |
| `test_object_storage.py` | Unit and service | 2 |
| `test_observability.py` | API | 5 |
| `test_outlook_auth.py` | Unit and service | 6 |
| `test_outlook_client.py` | API | 28 |
| `test_outlook_mailbox.py` | API | 10 |
| `test_outlook_send_gating.py` | Unit and service | 6 |
| `test_outlook_sync_service.py` | Unit and service | 10 |
| `test_output_guardrail.py` | Security and RBAC | 10 |
| `test_password_change.py` | Security and RBAC | 5 |
| `test_password_reset.py` | Security and RBAC | 5 |
| `test_patient_form_link.py` | API | 59 |
| `test_patient_form_service.py` | Unit and service | 13 |
| `test_patient_model.py` | Unit and service | 4 |
| `test_patient_service.py` | Unit and service | 13 |
| `test_patients.py` | API | 17 |
| `test_permission_grants.py` | Security and RBAC | 8 |
| `test_permissions.py` | Security and RBAC | 19 |
| `test_provisional_patient.py` | Unit and service | 4 |
| `test_provisional_purge.py` | Database-only | 13 |
| `test_rag_answer.py` | Unit and service | 7 |
| `test_rag_gating.py` | Unit and service | 3 |
| `test_rag_pipeline.py` | Database-only | 5 |
| `test_rag_retrieval.py` | Database-only | 17 |
| `test_rag_route.py` | API | 8 |
| `test_rbac_enforcement.py` | Security and RBAC | 441 |
| `test_rbac_registry.py` | Security and RBAC | 7 |
| `test_reply_gate.py` | Unit and service | 27 |
| `test_reply_parsing.py` | Unit and service | 9 |
| `test_require_any_permission.py` | Security and RBAC | 3 |
| `test_require_permission.py` | Security and RBAC | 2 |
| `test_review_actions.py` | API | 23 |
| `test_review_backfill.py` | Unit and service | 6 |
| `test_review_intake.py` | API | 20 |
| `test_review_permissions.py` | Security and RBAC | 12 |
| `test_review_routing.py` | Unit and service | 18 |
| `test_scoping.py` | Security and RBAC | 10 |
| `test_seed_demo_appointments.py` | Unit and service | 9 |
| `test_seed_demo_patients.py` | Unit and service | 4 |
| `test_settings_admin_controls.py` | API | 15 |
| `test_settings_effects.py` | Unit and service | 5 |
| `test_settings_routes.py` | API | 10 |
| `test_settings_service.py` | Unit and service | 12 |
| `test_system_actor.py` | Unit and service | 5 |
| `test_task_lifecycle.py` | API | 19 |
| `test_task_override.py` | API | 2 |
| `test_task_routing_gate.py` | Unit and service | 7 |
| `test_task_routing_rules.py` | Unit and service | 11 |
| `test_tasks.py` | API | 17 |
| `test_text_extraction.py` | Unit and service | 3 |
| `test_transcription_quality.py` | Unit and service | 6 |
| `test_triage_routing.py` | API | 15 |
| `test_urgent_detection.py` | Unit and service | 47 |
| `test_user_roles.py` | Security and RBAC | 6 |
| `test_user_service.py` | API | 11 |
| `test_voice_twilio.py` | API | 14 |
| `test_voicemail_graph.py` | Agent graph | 16 |
| `test_voicemail_hours.py` | Unit and service | 8 |
| `test_voicemail_model.py` | Unit and service | 3 |
| `test_voicemail_playback.py` | API | 10 |
| `test_voicemail_routes.py` | API | 5 |
| `test_voicemail_service.py` | Unit and service | 34 |
| `test_voicemail_sweep.py` | Unit and service | 9 |
| `test_write_reply.py` | API | 25 |
