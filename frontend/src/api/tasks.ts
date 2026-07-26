import { apiGet, apiPatch, apiPost } from "../lib/apiClient";
import type { Task, TaskBoard } from "./types";

interface RawTask {
  id: string; case_id: string; assigned_to: string | null;
  source: string; priority: string; status: string;
  created_at: string; updated_at: string;
}

function toTask(r: RawTask): Task {
  return {
    id: r.id, caseId: r.case_id, assignedTo: r.assigned_to,
    source: r.source as Task["source"], priority: r.priority as Task["priority"],
    status: r.status as Task["status"], createdAt: r.created_at, updatedAt: r.updated_at,
  };
}

export async function getTaskBoard(): Promise<TaskBoard> {
  const res = await apiGet<{ columns: Record<string, RawTask[]>; counts: TaskBoard["counts"] }>("/api/v1/tasks/board");
  return {
    columns: Object.fromEntries(Object.entries(res.columns).map(([k, v]) => [k, v.map(toTask)])),
    counts: res.counts,
  };
}

export async function listTasks(params: Record<string, unknown> = {}): Promise<Task[]> {
  const res = await apiGet<RawTask[]>("/api/v1/tasks", params);
  return res.map(toTask);
}

export async function getTask(taskId: string): Promise<Task> {
  return toTask(await apiGet<RawTask>(`/api/v1/tasks/${taskId}`));
}

export async function updateTask(taskId: string, payload: { status?: string; assigned_to?: string; priority?: string }): Promise<Task> {
  return toTask(await apiPatch<RawTask>(`/api/v1/tasks/${taskId}`, payload));
}

export async function createTask(payload: { case_id: string; source: string; priority?: string; assigned_to?: string }): Promise<Task> {
  return toTask(await apiPost<RawTask>("/api/v1/tasks", payload));
}
