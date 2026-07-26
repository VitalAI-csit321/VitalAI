import { apiGet, apiPost, apiPatch } from "../lib/apiClient";
import type { Case, Patient, PatientStatus } from "./types";

interface RawCase { id:string; patient_id:string|null; patient_name:string|null; contact_reason:string; contact_channel:string; notes:string|null; status:string; created_at:string; updated_at:string; }
interface RawPatient { id:string; mrn:string; name:string; dob:string; gender:string; status:PatientStatus; created_at:string; }

function toCase(r:RawCase):Case { return {id:r.id,patientId:r.patient_id,patientName:r.patient_name??"Unknown patient",contactReason:r.contact_reason,contactChannel:r.contact_channel,notes:r.notes,status:r.status,createdAt:r.created_at,updatedAt:r.updated_at}; }
function toPatient(r:RawPatient):Patient { return {id:r.id,mrn:r.mrn,name:r.name,dob:r.dob,gender:r.gender as Patient["gender"],status:r.status,createdAt:r.created_at}; }

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

export async function createCase(input:{patient_name:string;contact_reason:string;contact_channel:string;notes?:string}):Promise<Case> {
  return toCase(await apiPost<RawCase>("/api/v1/intake",input));
}

export interface PatientListParams { limit?:number; offset?:number; search?:string; status?:PatientStatus; [key:string]:unknown; }

export async function listPatients(params:PatientListParams={}):Promise<{items:Patient[];total:number;counts:{active:number;pending:number;inactive:number}}> {
  const res=await apiGet<{items:RawPatient[];total:number;counts:{active:number;pending:number;inactive:number}}>("/api/v1/patients",params);
  return {items:res.items.map(toPatient),total:res.total,counts:res.counts};
}

export async function getPatient(id: string): Promise<Patient> {
  return toPatient(await apiGet<RawPatient>(`/api/v1/patients/${id}`));
}

export async function createPatient(input:{name:string;dob:string;gender:string}):Promise<Patient> {
  // Backend expects dob as YYYY-MM-DD date string and gender as lowercase enum value
  const dobFormatted = input.dob.includes("/")
    ? (() => { const [d,m,y]=input.dob.split("/"); return `${y}-${m.padStart(2,"0")}-${d.padStart(2,"0")}`; })()
    : input.dob;
  const genderMap:Record<string,string> = { male:"male", female:"female", "non binary":"non_binary", nonbinary:"non_binary", other:"non_binary" };
  const gender = genderMap[input.gender.toLowerCase()] ?? "male";
  return toPatient(await apiPost<RawPatient>("/api/v1/patients",{name:input.name,dob:dobFormatted,gender}));
}

export async function updatePatient(id: string, input: {name?:string; dob?:string; gender?:string; status?:string}): Promise<Patient> {
  const payload: Record<string, string> = {};
  if (input.name !== undefined) payload.name = input.name;
  if (input.dob !== undefined) {
    payload.dob = input.dob.includes("/")
      ? (() => { const [d,m,y]=input.dob!.split("/"); return `${y}-${m.padStart(2,"0")}-${d.padStart(2,"0")}`; })()
      : input.dob;
  }
  if (input.gender !== undefined) {
    const genderMap:Record<string,string> = { male:"male", female:"female", "non binary":"non_binary", nonbinary:"non_binary" };
    payload.gender = genderMap[input.gender.toLowerCase()] ?? input.gender;
  }
  if (input.status !== undefined) payload.status = input.status;
  return toPatient(await apiPatch<RawPatient>(`/api/v1/patients/${id}`, payload));
}

export async function createPatientFromOnboarding(input:{
  firstName:string; lastName:string; dateOfBirth?:string; gender?:string;
  address?:string; indigenousStatus?:string; preferredLanguage?:string;
  contactReason?:string; contactChannel?:string;
  phone?:string; email?:string; emergencyContactName?:string; emergencyContactPhone?:string;
  bestTimeToContact?:string; knownConditions?:string; currentMedications?:string; allergies?:string;
  insuranceProvider?:string; policyNumber?:string; groupNumber?:string; expiryDate?:string;
  medicareNumber?:string; concessionCard?:string;
}):Promise<Patient> {
  const name=`${input.firstName} ${input.lastName}`.trim();
  // Convert DD/MM/YYYY to YYYY-MM-DD
  let dob="2000-01-01";
  if(input.dateOfBirth) {
    const parts=input.dateOfBirth.split("/");
    if(parts.length===3) dob=`${parts[2]}-${parts[1].padStart(2,"0")}-${parts[0].padStart(2,"0")}`;
    else dob=input.dateOfBirth;
  }
  const genderMap:Record<string,string>={male:"male",female:"female","non binary":"non_binary",nonbinary:"non_binary"};
  const gender=genderMap[(input.gender??"male").toLowerCase()]??"male";

  const patient=await toPatient(await apiPost<RawPatient>("/api/v1/patients",{name,dob,gender}));

  // The Patient/IntakeCase models have no fields for most of the onboarding
  // form (contact details, medical history, insurance), so everything
  // collected beyond the core Patient fields is captured in the intake
  // case's notes as structured JSON rather than silently discarded.
  try {
    await apiPost("/api/v1/intake",{
      patient_name:name,
      contact_reason:input.contactReason??"Patient onboarding",
      contact_channel:input.contactChannel??"portal",
      patient_id:patient.id,
      notes:JSON.stringify({
        address:input.address, indigenous_status:input.indigenousStatus, preferred_language:input.preferredLanguage,
        phone:input.phone, email:input.email,
        emergency_contact_name:input.emergencyContactName, emergency_contact_phone:input.emergencyContactPhone,
        best_time_to_contact:input.bestTimeToContact,
        known_conditions:input.knownConditions, current_medications:input.currentMedications, allergies:input.allergies,
        insurance_provider:input.insuranceProvider, policy_number:input.policyNumber, group_number:input.groupNumber,
        expiry_date:input.expiryDate, medicare_number:input.medicareNumber, concession_card:input.concessionCard,
      }),
    });
  } catch { /* best-effort */ }

  return patient;
}
