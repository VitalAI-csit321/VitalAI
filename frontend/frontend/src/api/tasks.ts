import { apiGet, apiPatch, apiPost } from "../lib/apiClient";
import type { Task, TaskBoard, TaskComment } from "./types";

interface RawTask {
  id: string; case_id: string; assigned_to: string | null;
  source: string; priority: string; status: string;
  target_queue: string | null; handover_context: string | null;
  created_at: string; updated_at: string;
}

interface RawTaskComment {
  id: string; task_id: string; author_id: string; body: string; created_at: string;
}

function toTask(r: RawTask): Task {
  return {
    id: r.id, caseId: r.case_id, assignedTo: r.assigned_to,
    source: r.source as Task["source"], priority: r.priority as Task["priority"],
    status: r.status as Task["status"],
    targetQueue: r.target_queue, handoverContext: r.handover_context,
    createdAt: r.created_at, updatedAt: r.updated_at,
  };
}

function toTaskComment(r: RawTaskComment): TaskComment {
  return { id: r.id, taskId: r.task_id, authorId: r.author_id, body: r.body, createdAt: r.created_at };
}

export async function getTaskBoard(): Promise<TaskBoard> {
  // No backend /tasks/board aggregation endpoint exists; group the flat
  // task list client-side instead.
  const tasks = await listTasks();
  const columns: Record<string, Task[]> = { pending: [], in_progress: [], escalated: [], completed: [] };
  for (const t of tasks) (columns[t.status] ??= []).push(t);
  return {
    columns,
    counts: {
      pending: columns.pending.length,
      in_progress: columns.in_progress.length,
      escalated: columns.escalated.length,
      completed: columns.completed.length,
    },
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

export async function listComments(taskId: string): Promise<TaskComment[]> {
  const res = await apiGet<RawTaskComment[]>(`/api/v1/tasks/${taskId}/comments`);
  return res.map(toTaskComment);
}

export async function addComment(taskId: string, body: string): Promise<TaskComment> {
  return toTaskComment(await apiPost<RawTaskComment>(`/api/v1/tasks/${taskId}/comments`, { body }));
}
