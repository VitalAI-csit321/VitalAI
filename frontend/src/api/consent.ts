import { apiGet, apiPost, type ApiPage } from "../lib/apiClient";
import { placeholderConsentForms } from "./_placeholder";
import type { Consent, ConsentQueueRow, ConsentQueueStatus } from "./types";

interface RawConsent {
  id: string;
  case_id: string;
  status: Consent["status"];
  captured_at: string | null;
  consent_type: string;
  notes: string | null;
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

export async function captureConsent(consentId: string): Promise<Consent> {
  return toConsent(await apiPost<RawConsent>(`/api/v1/consent/${consentId}/capture`));
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
function toQueueStatus(status: Consent["status"]): ConsentQueueStatus {
  if (status === "captured") return "complete";
  if (status === "withdrawn") return "review";
  return "pending";
}

interface RawCaseLite {
  id: string;
  patient_name: string;
  created_at: string;
}

export async function listConsentQueue(): Promise<ConsentQueueRow[]> {
  const cases = await apiGet<ApiPage<RawCaseLite>>("/api/v1/intake", { limit: 12 });
  const rows = await Promise.all(
    cases.items.map(async (c, i): Promise<ConsentQueueRow> => {
      const consent = await getConsentForCase(c.id);
      return {
        id: consent?.id ?? c.id,
        patientName: c.patient_name,
        form: placeholderConsentForms[i % placeholderConsentForms.length],
        submitted: c.created_at,
        status: consent ? toQueueStatus(consent.status) : "pending",
      };
    }),
  );
  return rows;
}
