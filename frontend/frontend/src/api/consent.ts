import { apiGet, apiPost } from "../lib/apiClient";
import type { Consent, ConsentFormSnapshot, ConsentQueueRow, ConsentQueueStatus } from "./types";

interface RawConsent {
  id: string;
  case_id: string;
  status: Consent["status"];
  captured_at: string | null;
  consent_type: string;
  notes: string | null;
  form_snapshot: ConsentFormSnapshot | null;
  created_at: string;
  updated_at: string;
}

function toConsent(raw: RawConsent): Consent {
  return {
    id: raw.id,
    caseId: raw.case_id,
    status: raw.status,
    capturedAt: raw.captured_at,
    consentType: raw.consent_type,
    notes: raw.notes,
    formSnapshot: raw.form_snapshot,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  };
}

// consentId names one record; without it, the case's latest.
export async function getConsentForCase(caseId: string, consentId?: string): Promise<Consent | null> {
  try {
    return toConsent(
      await apiGet<RawConsent>(`/api/v1/consent/by-case/${caseId}`, { consent_id: consentId }),
    );
  } catch {
    return null;
  }
}

export async function createConsent(input: {
  case_id: string;
  consent_type?: string;
  notes?: string;
}): Promise<Consent> {
  return toConsent(await apiPost<RawConsent>("/api/v1/consent", input));
}

export async function captureConsent(
  consentId: string,
  formSnapshot?: ConsentFormSnapshot,
): Promise<Consent> {
  return toConsent(
    await apiPost<RawConsent>(`/api/v1/consent/${consentId}/capture`, {
      form_snapshot: formSnapshot ?? null,
    }),
  );
}

export async function resolveConsentReview(
  consentId: string,
  formSnapshot: ConsentFormSnapshot,
): Promise<Consent> {
  return toConsent(
    await apiPost<RawConsent>(`/api/v1/consent/${consentId}/resolve-review`, {
      form_snapshot: formSnapshot,
    }),
  );
}

// checks answers the statements already on the record, in order; signature
// only when the patient did not sign online.
export async function verifyConsent(
  consentId: string,
  finish?: { checks: boolean[]; signature?: string },
): Promise<Consent> {
  return toConsent(await apiPost<RawConsent>(`/api/v1/consent/${consentId}/verify`, finish));
}

export const CONSENT_TYPES: { value: string; label: string }[] = [
  { value: "general_treatment", label: "General treatment" },
  { value: "surgical_procedure", label: "Surgical procedure" },
  { value: "data_sharing", label: "Data sharing" },
  { value: "research_study", label: "Research study" },
];

// Types staff never create by hand, so not offered in CONSENT_TYPES.
const OTHER_TYPE_LABELS: Record<string, string> = { online_registration: "Online registration" };

export function consentTypeLabel(value: string): string {
  return CONSENT_TYPES.find((t) => t.value === value)?.label ?? OTHER_TYPE_LABELS[value] ?? value;
}

export async function listConsentsForPatient(patientId: string): Promise<Consent[]> {
  const raw = await apiGet<RawConsent[]>("/api/v1/consent", { patient_id: patientId });
  return raw.map(toConsent);
}

export async function withdrawConsent(consentId: string): Promise<Consent> {
  return toConsent(await apiPost<RawConsent>(`/api/v1/consent/${consentId}/withdraw`));
}

// ── Consent queue (design 6) ──────────────────────────────────────────────
// SEAM: the design's queue joins consent + patient name + a "form" label +
// submitted date. The backend has no such list endpoint and no form concept, so
// we build the queue from recent cases and their consent record, projecting the
// real ConsentStatus onto the queue's pending/review/complete display states.
// The form label is placeholder until a forms backend exists.
// The queue row has no form snapshot, so it cannot ask whether every check
// was ticked; "captured" is complete here and the detail view still reviews
// the snapshot.
function queueStatusFor(status: Consent["status"], capturedAt: string | null): ConsentQueueStatus {
  if (status === "captured") return capturedAt ? "complete" : "review";
  if (status === "withdrawn") return "review";
  return "pending";
}

interface RawConsentQueueRow {
  id: string;
  case_id: string;
  patient_name: string | null;
  consent_type: string;
  status: Consent["status"];
  created_at: string;
  captured_at: string | null;
}

// Real consent records. This used to list the 12 most recent intake cases
// instead, label each with a placeholder form name cycled by row index, and
// show every case without a record as "pending", which told staff consent was
// awaited from people who had never been asked.
export async function listConsentQueue(limit = 50, offset = 0): Promise<ConsentQueueRow[]> {
  const page = await apiGet<{ items: RawConsentQueueRow[]; total: number }>(
    "/api/v1/consent/queue",
    { limit, offset },
  );
  return page.items.map((r) => ({
    id: r.id,
    caseId: r.case_id,
    patientName: r.patient_name ?? "Unknown patient",
    form: consentTypeLabel(r.consent_type),
    consentType: r.consent_type,
    submitted: r.created_at,
    status: queueStatusFor(r.status, r.captured_at),
  }));
}
