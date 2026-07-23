import { apiGet, apiPost, type ApiPage } from "../lib/apiClient";
import { placeholderPatientFields } from "./_placeholder";
import type { Case, Patient } from "./types";

interface RawCase {
  id: string;
  patient_name: string;
  contact_reason: string;
  contact_channel: string;
  notes: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

function toCase(raw: RawCase): Case {
  return {
    id: raw.id,
    patientName: raw.patient_name,
    contactReason: raw.contact_reason,
    contactChannel: raw.contact_channel,
    notes: raw.notes,
    status: raw.status,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  };
}

export interface CaseListParams {
  limit?: number;
  offset?: number;
  status?: string[];
  channel?: string;
  search?: string;
  [key: string]: unknown;
}

export async function listCases(params: CaseListParams = {}): Promise<ApiPage<Case>> {
  const page = await apiGet<ApiPage<RawCase>>("/api/v1/intake", params);
  return { ...page, items: page.items.map(toCase) };
}

export async function getCase(id: string): Promise<Case> {
  return toCase(await apiGet<RawCase>(`/api/v1/intake/${id}`));
}

export async function createCase(input: {
  patient_name: string;
  contact_reason: string;
  contact_channel: string;
  notes?: string;
}): Promise<Case> {
  return toCase(await apiPost<RawCase>("/api/v1/intake", input));
}

export async function getStatusCounts(): Promise<Record<string, number>> {
  const res = await apiGet<{ status_counts: Record<string, number> }>("/api/v1/intake/summary");
  return res.status_counts;
}

// ── Patients adapter ──────────────────────────────────────────────────────
// SEAM: there is no patient entity in the backend yet. We derive the patient
// list from intake cases and fill MRN/DOB/gender/status from the placeholder
// source. When a real patient database is added, replace the body of
// listPatients / createPatient with calls to it and delete the placeholder
// import — the Patient type and every consumer stay unchanged.
// Onboarding stores the fields the backend can't model as a JSON blob in the
// case notes. Read them back when present so a patient created through the
// wizard round-trips their real details instead of showing synthesized ones.
function readOnboardingExtras(
  notes: string | null,
): { dateOfBirth?: string; gender?: string } {
  if (!notes) return {};
  try {
    const parsed = JSON.parse(notes) as Record<string, unknown>;
    const dob = typeof parsed.date_of_birth === "string" ? parsed.date_of_birth : undefined;
    const gender = typeof parsed.gender === "string" ? parsed.gender : undefined;
    return { dateOfBirth: dob, gender };
  } catch {
    // Notes are free text for cases not created via onboarding — expected.
    return {};
  }
}

export async function listPatients(params: {
  limit?: number;
  offset?: number;
  search?: string;
} = {}): Promise<ApiPage<Patient>> {
  const page = await listCases(params);
  const items: Patient[] = page.items.map((c, i) => {
    const synthesized = placeholderPatientFields(c.id, page.offset + i);
    const real = readOnboardingExtras(c.notes);
    return {
      id: c.id,
      name: c.patientName,
      mrn: synthesized.mrn,
      // Prefer anything genuinely captured; fall back to synthesized only for
      // records that predate onboarding or came from another channel.
      dateOfBirth: real.dateOfBirth || synthesized.dateOfBirth,
      gender: real.gender || synthesized.gender,
      status: synthesized.status,
    };
  });
  return { ...page, items };
}

// Patient onboarding (design 5) collects fields the backend can't store yet.
// We persist what it CAN — the patient name becomes an intake case — and accept
// the rest into the case notes so nothing entered is silently lost. When the
// real patient table exists, swap this for a proper create-patient call.
export async function createPatientFromOnboarding(input: {
  firstName: string;
  lastName: string;
  dateOfBirth?: string;
  gender?: string;
  address?: string;
  indigenousStatus?: string;
  preferredLanguage?: string;
  contactReason?: string;
  contactChannel?: string;
}): Promise<Case> {
  const name = `${input.firstName} ${input.lastName}`.trim();
  const extras = {
    date_of_birth: input.dateOfBirth || null,
    gender: input.gender || null,
    address: input.address || null,
    indigenous_status: input.indigenousStatus || null,
    preferred_language: input.preferredLanguage || null,
  };
  return createCase({
    patient_name: name,
    contact_reason: input.contactReason || "Patient onboarding",
    contact_channel: input.contactChannel || "portal",
    notes: JSON.stringify(extras),
  });
}
