import { apiGet, apiPost, type ApiPage } from "../lib/apiClient";
import { placeholderConsentForms } from "./_placeholder";
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

export async function getConsentForCase(caseId: string): Promise<Consent | null> {
  try {
    return toConsent(await apiGet<RawConsent>(`/api/v1/consent/by-case/${caseId}`));
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

export const CONSENT_TYPES: { value: string; label: string }[] = [
  { value: "general_treatment", label: "General Treatment" },
  { value: "surgical_procedure", label: "Surgical Procedure" },
  { value: "data_sharing", label: "Data Sharing" },
  { value: "research_study", label: "Research Study" },
];

export function consentTypeLabel(value: string): string {
  return CONSENT_TYPES.find((t) => t.value === value)?.label ?? value;
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
function toQueueStatus(consent: Consent): ConsentQueueStatus {
  if (consent.status === "captured") {
    const allChecked = consent.formSnapshot?.checks.every((c) => c.checked) ?? true;
    return allChecked ? "complete" : "review";
  }
  if (consent.status === "withdrawn") return "review";
  return "pending";
}

interface RawCaseLite {
  id: string;
  patient_name: string | null;
  created_at: string;
}

export async function listConsentQueue(): Promise<ConsentQueueRow[]> {
  const cases = await apiGet<ApiPage<RawCaseLite>>("/api/v1/intake", { limit: 12 });
  const rows = await Promise.all(
    cases.items.map(async (c, i): Promise<ConsentQueueRow> => {
      const consent = await getConsentForCase(c.id);
      return {
        id: consent?.id ?? c.id,
        caseId: c.id,
        patientName: c.patient_name ?? "Unknown patient",
        form: placeholderConsentForms[i % placeholderConsentForms.length],
        submitted: c.created_at,
        status: consent ? toQueueStatus(consent) : "pending",
      };
    }),
  );
  return rows;
}
