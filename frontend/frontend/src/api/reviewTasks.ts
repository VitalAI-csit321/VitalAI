import { apiGet, apiPost } from "../lib/apiClient";

export interface RawReviewTask {
  id: string; created_at: string; case_id: string; triage_id: string | null;
  task_type: string; status: "pending" | "in_progress" | "completed" | "cancelled" | "escalated";
  priority: "low" | "medium" | "high";
  target_role: string | null; assigned_to: string | null; notes: string | null;
}

export async function listReviewTasks(params: { limit?: number; offset?: number } = {}): Promise<{ items: RawReviewTask[]; total: number }> {
  return apiGet<{ items: RawReviewTask[]; total: number }>("/api/v1/human-review", params);
}

export async function claimReviewTask(id: string): Promise<RawReviewTask> {
  return apiPost<RawReviewTask>(`/api/v1/human-review/${id}/claim`);
}

export async function completeReviewTask(id: string, notes: string | null): Promise<RawReviewTask> {
  return apiPost<RawReviewTask>(`/api/v1/human-review/${id}/complete`, { notes });
}

export async function rejectReviewTask(id: string, notes: string | null): Promise<RawReviewTask> {
  return apiPost<RawReviewTask>(`/api/v1/human-review/${id}/reject`, { notes });
}

export async function escalateReviewTask(id: string, notes: string | null): Promise<RawReviewTask> {
  return apiPost<RawReviewTask>(`/api/v1/human-review/${id}/escalate`, { notes });
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
