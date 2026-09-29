import { apiDelete, apiGet, apiPost } from "../lib/apiClient";
import { listAppointments } from "./appointments";
import { getTaskBoard } from "./tasks";
import type { CurrentUser, DashboardSummary, Message } from "./types";
import { toDateInputValue } from "../components/calendarHelpers";

const TASK_TYPE_LABEL: Record<string, string> = {
  triage_review: "HITL Approval",
  consent_review: "Consent Review",
  escalation_review: "Escalation Review",
  routing_review: "Routing Review",
};

// Appointment counts for the current Monday-based week, for the dashboard's
// Workflow Status chart. Same week definition and list-and-bucket approach
// CalendarPage's week view already uses (see its weekStart calc) instead of a
// trailing-past window, which would miss this week's upcoming appointments.
async function getWeeklyAppointmentCounts(): Promise<DashboardSummary["workflowByDay"]> {
  const today = new Date();
  const dow = (today.getDay() + 6) % 7; // Monday-based
  const rangeStart = new Date(today); rangeStart.setDate(rangeStart.getDate() - dow); rangeStart.setHours(0, 0, 0, 0);
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(rangeStart);
    d.setDate(d.getDate() + i);
    return d;
  });
  const rangeEnd = new Date(rangeStart); rangeEnd.setDate(rangeEnd.getDate() + 7);

  const { items } = await listAppointments({
    dateFrom: rangeStart.toISOString(), dateTo: rangeEnd.toISOString(), limit: 200,
  });
  const countsByDate = new Map<string, number>();
  for (const a of items) {
    const key = toDateInputValue(new Date(a.timeSlot));
    countsByDate.set(key, (countsByDate.get(key) ?? 0) + 1);
  }
  return days.map(d => {
    const date = toDateInputValue(d);
    return { day: d.toLocaleDateString("en-US", { weekday: "short" }), date, value: countsByDate.get(date) ?? 0 };
  });
}

export async function getDashboard(user: CurrentUser | null): Promise<DashboardSummary> {
  // Skip what this user may not read: the backend logs every refused call as a
  // BLOCKED audit event. Doctors lack view_queue; read_audit is admin or a grant.
  const canViewQueue = user?.role !== "doctor";
  const canReadAudit = user?.role === "admin" || (user?.grantedPermissions.includes("read_audit") ?? false);
  const [intakeRes, auditRes, pendingRes, inProgressRes, escalatedRes, reviewListRes, weeklyRes] =
    await Promise.allSettled([
      canViewQueue ? apiGet<{items:unknown[];total:number}>("/api/v1/intake?limit=1") : Promise.reject(),
      canReadAudit ? apiGet<{total:number}>("/api/v1/audit?limit=1") : Promise.reject(),
      apiGet<{total:number}>("/api/v1/human-review", {limit:1, status:"pending"}),
      apiGet<{total:number}>("/api/v1/human-review", {limit:1, status:"in_progress"}),
      // Same source as EscalationsPage's own count (getTaskBoard) -- the
      // /escalations page is built on task routing (/api/v1/tasks), a
      // different model from human-review approvals, which has its own
      // unrelated "escalated" status.
      canViewQueue ? getTaskBoard() : Promise.reject(),
      apiGet<{items:{id:string;task_type:string;status:string;patient_name:string|null}[];total:number}>(
        "/api/v1/human-review", {limit:20}
      ),
      getWeeklyAppointmentCounts(),
    ]);

  const openCases = intakeRes.status==="fulfilled" ? intakeRes.value.total : null;
  const auditEvents = auditRes.status==="fulfilled" ? auditRes.value.total : null;
  const pending = pendingRes.status==="fulfilled" ? pendingRes.value.total : 0;
  const inProgress = inProgressRes.status==="fulfilled" ? inProgressRes.value.total : 0;
  const escalated = escalatedRes.status==="fulfilled" ? escalatedRes.value.counts.escalated : null;
  const workflowByDay = weeklyRes.status==="fulfilled" ? weeklyRes.value : [];

  // Pending Reviews list: real human-review tasks; the list response carries
  // each task's patient name from its linked case.
  let pendingReviews: DashboardSummary["pendingReviews"] = [];
  if (reviewListRes.status === "fulfilled") {
    pendingReviews = reviewListRes.value.items
      .filter(t => t.status === "pending" || t.status === "in_progress")
      .slice(0, 4)
      .map(task => ({
        id: task.id,
        name: task.patient_name ?? "Unknown patient",
        kind: TASK_TYPE_LABEL[task.task_type] ?? task.task_type,
        isNew: task.status === "pending",
      }));
  }

  return {
    openCases,
    awaitingApproval:
      pendingRes.status === "fulfilled" || inProgressRes.status === "fulfilled" ? pending + inProgress : null,
    escalations: escalated,
    auditEvents,
    workflowByDay,
    pendingReviews,
  };
}

export async function listMessages(archived = false): Promise<Message[]> {
  const res = await apiGet<{ items: Message[]; total: number }>("/api/v1/inbox", { archived });
  return res.items;
}

// Approves a pending draft reply (email.draft_reply approval), marking it sent.
// editedDraft/emailId/taskId let the operator send a corrected version of the
// AI draft instead of the original; resolved_payload fully replaces the
// approval's stored payload, so all three fields the executor needs must be
// passed together whenever the text was edited.
export async function approveDraft(
  approvalId: string,
  edited?: { draft: string; emailId: string; taskId: string },
): Promise<void> {
  await apiPost(`/api/v1/approvals/${approvalId}/approve`, {
    resolved_payload: edited
      ? { draft: edited.draft, email_id: edited.emailId, task_id: edited.taskId }
      : undefined,
  });
}

export async function escalateMessage(taskId: string, reason?: string): Promise<void> {
  await apiPost(`/api/v1/tasks/${taskId}/escalate`, reason ? { reason } : {});
}

export async function archiveMessage(taskId: string): Promise<void> {
  await apiPost(`/api/v1/tasks/${taskId}/archive`);
}

export async function markMessageRead(taskId: string): Promise<void> {
  await apiPost(`/api/v1/tasks/${taskId}/read`);
}

export async function deleteMessage(taskId: string): Promise<void> {
  await apiDelete(`/api/v1/tasks/${taskId}`);
}
