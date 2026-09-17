import { apiGet, apiPost, apiPatch } from "../lib/apiClient";
import type { Case, Patient, PatientStatus } from "./types";

interface RawCase { id:string; patient_id:string|null; patient_name:string|null; contact_reason:string; contact_channel:string; notes:string|null; status:string; created_at:string; updated_at:string; }

interface RawPatient {
  id:string; mrn:string; name:string; dob:string; gender:string; status:PatientStatus; created_at:string;
  address: string | null; indigenous_status: string | null; preferred_language: string | null;
  phone: string | null; email: string | null;
  emergency_contact_name: string | null; emergency_contact_phone: string | null;
  preferred_communication: string | null; best_time_to_contact: string | null;
  known_conditions: string | null; current_medications: string | null; allergies: string | null;
  insurance_provider: string | null; policy_number: string | null; group_number: string | null;
  insurance_expiry: string | null; medicare_number: string | null; concession_card: string | null;
  missing_fields: string[];
}

function toCase(r:RawCase):Case { return {id:r.id,patientId:r.patient_id,patientName:r.patient_name??"Unknown patient",contactReason:r.contact_reason,contactChannel:r.contact_channel,notes:r.notes,status:r.status,createdAt:r.created_at,updatedAt:r.updated_at}; }

function toPatient(r:RawPatient):Patient {
  return {
    id:r.id, mrn:r.mrn, name:r.name, dob:r.dob, gender:r.gender as Patient["gender"], status:r.status, createdAt:r.created_at,
    address:r.address, indigenousStatus:r.indigenous_status, preferredLanguage:r.preferred_language,
    phone:r.phone, email:r.email,
    emergencyContactName:r.emergency_contact_name, emergencyContactPhone:r.emergency_contact_phone,
    preferredCommunication:r.preferred_communication, bestTimeToContact:r.best_time_to_contact,
    knownConditions:r.known_conditions, currentMedications:r.current_medications, allergies:r.allergies,
    insuranceProvider:r.insurance_provider, policyNumber:r.policy_number, groupNumber:r.group_number,
    expiryDate:r.insurance_expiry, medicareNumber:r.medicare_number, concessionCard:r.concession_card,
    missingFields:r.missing_fields,
  };
}

export async function listCases(params:Record<string,unknown>={}):Promise<{items:Case[];total:number}> {
  const page=await apiGet<{items:RawCase[];total:number}>("/api/v1/intake",params);
  return {...page,items:page.items.map(toCase)};
}

export async function getCase(id: string): Promise<Case> {
  return toCase(await apiGet<RawCase>(`/api/v1/intake/${id}`));
}

export async function listCasesForPatient(patientId: string): Promise<Case[]> {
  const page = await apiGet<{ items: RawCase[]; total: number }>("/api/v1/intake", { limit: 100 });
  return page.items
    .filter(c => c.patient_id === patientId)
    .map(toCase)
    .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
}

export async function findLatestCaseForPatient(patientId: string): Promise<Case | null> {
  const cases = await listCasesForPatient(patientId);
  return cases[0] ?? null;
}

export async function createCase(input:{patient_id:string;patient_name:string;contact_reason:string;contact_channel:string;notes?:string}):Promise<Case> {
  return toCase(await apiPost<RawCase>("/api/v1/intake",input));
}

export interface PatientListParams { limit?:number; offset?:number; search?:string; status?:PatientStatus; sort?:"missing_fields"; [key:string]:unknown; }

export async function listPatients(params:PatientListParams={}):Promise<{items:Patient[];total:number;counts:{active:number;pending:number;inactive:number}}> {
  const res=await apiGet<{items:RawPatient[];total:number;counts:{active:number;pending:number;inactive:number}}>("/api/v1/patients",params);
  return {items:res.items.map(toPatient),total:res.total,counts:res.counts};
}

export async function getPatient(id: string): Promise<Patient> {
  return toPatient(await apiGet<RawPatient>(`/api/v1/patients/${id}`));
}

export async function createPatient(input:{name:string;dob:string;gender:string}):Promise<Patient> {
  const dobFormatted = ddmmyyyyToIso(input.dob);
  const genderMap:Record<string,string> = { male:"male", female:"female", "non binary":"non_binary", nonbinary:"non_binary", other:"non_binary" };
  const gender = genderMap[input.gender.toLowerCase()] ?? "male";
  return toPatient(await apiPost<RawPatient>("/api/v1/patients",{name:input.name,dob:dobFormatted,gender}));
}

// Converts a DD/MM/YYYY string (the wizard/edit forms' display format) to
// YYYY-MM-DD (what the backend's `date` fields expect). A value already in
// ISO form (no "/") passes through unchanged.
function ddmmyyyyToIso(s: string): string {
  if (!s.includes("/")) return s;
  const [d, m, y] = s.split("/");
  return `${y}-${m.padStart(2,"0")}-${d.padStart(2,"0")}`;
}

// The 18 profile fields, in the camelCase shape both the onboarding wizard's
// form state and the edit page's form state use. Shared by
// createPatientFromOnboarding and updatePatient so the two never drift.
export interface ProfileFields {
  address?: string; indigenousStatus?: string; preferredLanguage?: string;
  phone?: string; email?: string; emergencyContactName?: string; emergencyContactPhone?: string;
  preferredCommunication?: string; bestTimeToContact?: string;
  knownConditions?: string; currentMedications?: string; allergies?: string;
  insuranceProvider?: string; policyNumber?: string; groupNumber?: string; expiryDate?: string;
  medicareNumber?: string; concessionCard?: string;
}

function profileFieldsToPayload(input: ProfileFields): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  if (input.address !== undefined) payload.address = input.address;
  if (input.indigenousStatus !== undefined) payload.indigenous_status = input.indigenousStatus;
  if (input.preferredLanguage !== undefined) payload.preferred_language = input.preferredLanguage;
  if (input.phone !== undefined) payload.phone = input.phone;
  if (input.email !== undefined) payload.email = input.email;
  if (input.emergencyContactName !== undefined) payload.emergency_contact_name = input.emergencyContactName;
  if (input.emergencyContactPhone !== undefined) payload.emergency_contact_phone = input.emergencyContactPhone;
  if (input.preferredCommunication !== undefined) payload.preferred_communication = input.preferredCommunication;
  if (input.bestTimeToContact !== undefined) payload.best_time_to_contact = input.bestTimeToContact;
  if (input.knownConditions !== undefined) payload.known_conditions = input.knownConditions;
  if (input.currentMedications !== undefined) payload.current_medications = input.currentMedications;
  if (input.allergies !== undefined) payload.allergies = input.allergies;
  if (input.insuranceProvider !== undefined) payload.insurance_provider = input.insuranceProvider;
  if (input.policyNumber !== undefined) payload.policy_number = input.policyNumber;
  if (input.groupNumber !== undefined) payload.group_number = input.groupNumber;
  if (input.expiryDate !== undefined) payload.insurance_expiry = input.expiryDate ? ddmmyyyyToIso(input.expiryDate) : null;
  if (input.medicareNumber !== undefined) payload.medicare_number = input.medicareNumber;
  if (input.concessionCard !== undefined) payload.concession_card = input.concessionCard;
  return payload;
}

export async function updatePatient(
  id: string,
  input: {name?:string; dob?:string; gender?:string; status?:string} & ProfileFields,
): Promise<Patient> {
  const payload: Record<string, unknown> = profileFieldsToPayload(input);
  if (input.name !== undefined) payload.name = input.name;
  if (input.dob !== undefined) payload.dob = ddmmyyyyToIso(input.dob);
  if (input.gender !== undefined) {
    const genderMap:Record<string,string> = { male:"male", female:"female", "non binary":"non_binary", nonbinary:"non_binary" };
    payload.gender = genderMap[input.gender.toLowerCase()] ?? input.gender;
  }
  if (input.status !== undefined) payload.status = input.status;
  return toPatient(await apiPatch<RawPatient>(`/api/v1/patients/${id}`, payload));
}

export async function createPatientFromOnboarding(input:{
  firstName:string; lastName:string; dateOfBirth?:string; gender?:string;
  contactReason?:string; contactChannel?:string;
} & ProfileFields):Promise<Patient> {
  const name=`${input.firstName} ${input.lastName}`.trim();
  const dob = input.dateOfBirth ? ddmmyyyyToIso(input.dateOfBirth) : "2000-01-01";
  const genderMap:Record<string,string>={male:"male",female:"female","non binary":"non_binary",nonbinary:"non_binary"};
  const gender=genderMap[(input.gender??"male").toLowerCase()]??"male";

  const patient = await toPatient(await apiPost<RawPatient>("/api/v1/patients", {
    name, dob, gender, ...profileFieldsToPayload(input),
  }));

  try {
    await apiPost("/api/v1/intake",{
      patient_name:name,
      contact_reason:input.contactReason??"Patient onboarding",
      contact_channel:input.contactChannel??"portal",
      patient_id:patient.id,
    });
  } catch { /* best-effort */ }

  return patient;
}
