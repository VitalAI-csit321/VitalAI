import { apiGet, apiPost } from "../lib/apiClient";

export const KIND_LABEL: Record<string, string> = {
  draft_approval: "Reply needs approval",
  routing_review: "Check the category",
  intent_review: "Classifier disagreement",
  identity_review: "Confirm who sent this",
  agent_failure: "Automation stopped",
  agent_handover: "Agent handed over",
  complaint_review: "Complaint needs a response",
  case_choice: "Which case does this belong to?",
  case_close: "Close this case?",
  prescription_request: "Repeat prescription",
  consent_review: "Consent review",
  triage_review: "Triage review",
  escalation_review: "Escalation review",
};

export interface RawReviewTask {
  // case_id is the contact; null for an item about a case (case_close), see episode_id.
  id: string; created_at: string; case_id: string | null; episode_id?: string | null; triage_id: string | null;
  task_type: string; status: "pending" | "in_progress" | "completed" | "cancelled" | "escalated";
  priority: "low" | "medium" | "high";
  target_role: string | null; assigned_to: string | null; notes: string | null;
  approval_id: string | null; inbox_task_id: string | null;
  details: {
    escalation?: { by: string; by_role?: string; note: string };
    category?: string;
    candidates?: string[];
    outcome?: string;
    stage?: string;
    suggested_episode_id?: string;
  } | null;
  // Only the list endpoint fills these (from the linked case and its audit trail).
  contact_reason?: string | null; patient_name?: string | null;
  created_by?: string | null; assigned_to_name?: string | null;
  owner_label?: string | null; channel?: string | null; due_at?: string | null;
  candidates?: { id: string; name: string; dob: string }[] | null;
  // Cases (M4): the case a case_close item is about, the cases a case_choice offers.
  case_title?: string | null;
  case_candidates?: { id: string; title: string; last_activity_at: string }[] | null;
}

// pending, in_progress, escalated are all still "open"; completed and
// cancelled are closed. Used to gate actions and the source-message fetch.
export const isOpen = (t: RawReviewTask) =>
  t.status === "pending" || t.status === "in_progress" || t.status === "escalated";

export async function listReviewTasks(params: { limit?: number; offset?: number } = {}): Promise<{ items: RawReviewTask[]; total: number }> {
  return apiGet<{ items: RawReviewTask[]; total: number }>("/api/v1/human-review", params);
}

export async function claimReviewTask(id: string): Promise<RawReviewTask> {
  return apiPost<RawReviewTask>(`/api/v1/human-review/${id}/claim`);
}

export async function completeReviewTask(id: string, notes: string | null): Promise<RawReviewTask> {
  return apiPost<RawReviewTask>(`/api/v1/human-review/${id}/complete`, { notes });
}

// Dismiss. Refused 409 by the server for a draft_approval item -- reject
// that kind through the linked approval instead (see api/misc.ts::rejectDraft).
export async function dismissReviewTask(id: string, notes: string): Promise<RawReviewTask> {
  return apiPost<RawReviewTask>(`/api/v1/human-review/${id}/reject`, { notes });
}

export async function escalateReviewTask(id: string, notes: string): Promise<RawReviewTask> {
  return apiPost<RawReviewTask>(`/api/v1/human-review/${id}/escalate`, { notes });
}

export async function rerouteReviewTask(id: string, category: string): Promise<RawReviewTask> {
  return apiPost<RawReviewTask>(`/api/v1/human-review/${id}/reroute`, { category });
}

export async function linkReviewPatient(id: string, patientId: string | null): Promise<RawReviewTask> {
  return apiPost<RawReviewTask>(`/api/v1/human-review/${id}/link-patient`, { patient_id: patientId });
}

export async function reassignReviewTask(id: string, doctorId: string): Promise<RawReviewTask> {
  return apiPost<RawReviewTask>(`/api/v1/human-review/${id}/reassign`, { doctor_id: doctorId });
}

export interface CreateReviewTaskInput {
  task_type: string;
  contact_reason: string;
  priority?: "low" | "medium" | "high";
  assigned_to?: string | null;
  reviewed?: boolean;
  notes?: string | null;
}

export async function createReviewTask(input: CreateReviewTaskInput): Promise<RawReviewTask> {
  return apiPost<RawReviewTask>("/api/v1/human-review", input);
}

// "Which case does this belong to?": an offered case, or null for a new one.
export async function chooseCase(id: string, episodeId: string | null): Promise<RawReviewTask> {
  return apiPost<RawReviewTask>(`/api/v1/human-review/${id}/choose-case`, { episode_id: episodeId });
}

// "Close this case?": close with the outcome note, or keep it open for another quiet spell.
export async function answerCaseClose(id: string, close: boolean, note: string | null): Promise<RawReviewTask> {
  return apiPost<RawReviewTask>(`/api/v1/human-review/${id}/case-close`, { close, note });
}
