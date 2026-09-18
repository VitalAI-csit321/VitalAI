"""doc_type -> access_scope, the one mapping both ingest paths read.

Moved here out of scripts/ingest_corpus.py so the HTTP upload path
(app/services/clinical_document_service.ingest_document) and the corpus batch
path cannot disagree about what a document type is worth protecting: the two
used to, with the upload path hardcoding "restricted" for everything it wrote.

Tiers mirror the generator's own DOC_CLASSIFICATION in "Dataset Generator
Code/Dataset_Generator.py": Low/Medium -> general, High -> restricted,
Critical -> sensitive. An unknown doc_type fails closed to restricted, never
general, so an unrecognised clinical document cannot leak to all staff.
"""

from __future__ import annotations

DOC_TYPE_TO_SCOPE = {
    "consultation": "restricted",
    "consultation_note": "restricted",
    "pathology_report": "restricted",
    "prescription": "restricted",
    "registration_form": "general",
    "appointment_history": "general",
    "referral_letter": "general",
    "care_plan": "restricted",
    "specialist_letter": "restricted",
    "hospital_discharge_summary": "restricted",
    "external_imaging_report": "restricted",
    "consent_record": "sensitive",
    # Org-wide (patient_id=NULL) doc types, ingested by scripts/ingest_org_profile.py
    # from "Organization Profile Review/". general = patient-facing, safe to quote
    # (the only org scope email_service.draft_reply's allowed_scopes=["general",
    # "restricted"] and /rag/query can both legitimately surface to a patient).
    # routing_rules/staff_directory/data_classification/guardrails are internal-only
    # (login usernames, routing internals) with no legitimate reason to reach a
    # patient reply, so they're "sensitive" -- a separate tier from the "restricted"
    # clinical-patient-data scope, unreachable by any current retrieval caller
    # (app.auth.scoping.allowed_scopes() never grants "sensitive"). Deliberately
    # inert until a future system-level caller opts into "sensitive" explicitly.
    "clinic_identity": "general",
    "policy_faq": "general",
    "routing_rules": "sensitive",
    "staff_directory": "sensitive",
    "data_classification": "sensitive",
    "guardrails": "sensitive",
}


def access_scope_for_doc_type(doc_type: str) -> str:
    return DOC_TYPE_TO_SCOPE.get(doc_type, "restricted")
