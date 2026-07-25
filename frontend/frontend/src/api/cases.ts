import { apiGet, apiPost, type ApiPage } from "../lib/apiClient";
import type { Case, Patient, PatientCounts, PatientStatus } from "./types";

interface RawCase { id: string; patient_name: string; contact_reason: string; contact_channel: string; notes: string | null; status: string; created_at: string; updated_at: string; }
interface RawPatient { id: string; mrn: string; name: string; dob: string; gender: string; status: PatientStatus; created_at: string; }

function toCase(r: RawCase): Case { return { id: r.id, patientName: r.patient_name, contactReason: r.contact_reason, contactChannel: r.contact_channel, notes: r.notes, status: r.status, createdAt: r.created_at, updatedAt: r.updated_at }; }
function toPatient(r: RawPatient): Patient { return { id: r.id, mrn: r.mrn, name: r.name, dob: r.dob, gender: r.gender as Patient["gender"], status: r.status, createdAt: r.created_at }; }

export interface CaseListParams { limit?: number; offset?: number; status?: string[]; channel?: string; search?: string; [key: string]: unknown; }

export async function listCases(params: CaseListParams = {}): Promise<ApiPage<Case>> {
  const page = await apiGet<ApiPage<RawCase>>("/api/v1/intake", params);
  return { ...page, items: page.items.map(toCase) };
}

export async function createCase(input: { patient_name: string; contact_reason: string; contact_channel: string; notes?: string }): Promise<Case> {
  return toCase(await apiPost<RawCase>("/api/v1/intake", input));
}

// Real patient entity now exists in the backend
export interface PatientListParams { limit?: number; offset?: number; search?: string; status?: PatientStatus; [key: string]: unknown; }

export async function listPatients(params: PatientListParams = {}): Promise<{ items: Patient[]; total: number; counts: PatientCounts }> {
  const res = await apiGet<{ items: RawPatient[]; total: number; counts: { active: number; pending: number; inactive: number } }>("/api/v1/patients", params);
  return { items: res.items.map(toPatient), total: res.total, counts: res.counts };
}

export async function createPatient(input: { name: string; dob: string; gender: string }): Promise<Patient> {
  return toPatient(await apiPost<RawPatient>("/api/v1/patients", input));
}

// Onboarding creates a real patient then an intake case
export async function createPatientFromOnboarding(input: {
  firstName: string; lastName: string; dateOfBirth?: string;
  gender?: string; address?: string; indigenousStatus?: string;
  preferredLanguage?: string; contactReason?: string; contactChannel?: string;
}): Promise<Patient> {
  const patient = await createPatient({
    name: `${input.firstName} ${input.lastName}`.trim(),
    dob: input.dateOfBirth || "2000-01-01",
    gender: input.gender?.toLowerCase().replace(" ", "_") || "male",
  });
  // Also create an intake case linked to the patient
  await createCase({
    patient_name: patient.name,
    contact_reason: input.contactReason || "Patient onboarding",
    contact_channel: input.contactChannel || "portal",
    notes: JSON.stringify({ patient_id: patient.id, address: input.address, indigenous_status: input.indigenousStatus, preferred_language: input.preferredLanguage }),
  });
  return patient;
}
