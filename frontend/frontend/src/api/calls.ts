import { apiGetBlob, apiPost, apiPostForm } from "../lib/apiClient";

export interface CallRouteResult {
  task_id: string;
  category: string;
  confidence: number;
  target_role: string;
  outcome: "auto_routed" | "auto_routed_flagged" | "human_review";
  override_reason: string | null;
}

export async function transcribeAudio(file: File): Promise<string> {
  const form = new FormData();
  form.append("audio", file);
  const res = await apiPostForm<{ transcript: string }>("/api/v1/calls/transcribe", form);
  return res.transcript;
}

// A logged call is its own contact (M4): the caller when known, and the case
// staff chose. With no case chosen, a clinical call joins one when routed.
export async function createCall(input: {
  patientId: string | null; episodeId: string | null; phoneNumber: string; transcript: string;
}): Promise<{ id: string }> {
  return apiPost<{ id: string }>("/api/v1/calls", {
    patient_id: input.patientId,
    episode_id: input.episodeId,
    phone_number: input.phoneNumber,
    transcript: input.transcript,
  });
}

export async function routeCall(callId: string): Promise<CallRouteResult> {
  return apiPost<CallRouteResult>(`/api/v1/calls/${callId}/route`, {});
}

export interface SimulateVoicemailInput {
  file: File;
  fromNumber: string;
  dobDigits: string;
  intentDigit: string;
  urgent: boolean;
}

export async function simulateVoicemail(input: SimulateVoicemailInput): Promise<{ call_id: string }> {
  const form = new FormData();
  form.append("audio", input.file);
  form.append("from_number", input.fromNumber);
  if (input.dobDigits) form.append("dob_digits", input.dobDigits);
  if (input.intentDigit) form.append("intent_digit", input.intentDigit);
  form.append("urgent", String(input.urgent));
  return apiPostForm<{ call_id: string }>("/api/v1/voicemails/simulate", form);
}

export async function fetchCallAudio(callId: string): Promise<Blob> {
  return apiGetBlob(`/api/v1/calls/${callId}/audio`);
}
