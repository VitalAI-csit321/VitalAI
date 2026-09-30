import { apiDelete, apiGet, apiPost } from "../lib/apiClient";
import { getDayView, listAppointments } from "./appointments";
import { KIND_LABEL } from "./reviewTasks";
import { getTaskBoard } from "./tasks";
import type { AttentionItem, CurrentUser, DashboardSummary, Message } from "./types";
import { toDateInputValue } from "../components/calendarHelpers";

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

type ReviewRow = {
  id: string; task_type: string; status: string; priority: string; created_at: string;
  patient_name: string | null; contact_reason?: string | null; case_title?: string | null;
};
const OPEN_REVIEW = new Set(["pending", "in_progress", "escalated"]);
const oldest = (dates: string[]) => (dates.length ? dates.reduce((a, b) => (a < b ? a : b)) : null);

export async function getDashboard(user: CurrentUser | null): Promise<DashboardSummary> {
  // Skip what this user may not read: the backend logs every refused call as a
  // BLOCKED audit event. Doctors lack view_queue, so no task board for them.
  const canViewQueue = user?.role !== "doctor";
  const [casesRes, pendingRes, inProgressRes, reviewEscalatedRes, boardRes, reviewListRes, weeklyRes, todayRes] =
    await Promise.allSettled([
      // Open cases (episodes of care, M4); every role reads them, a doctor only their own.
      apiGet<{items:unknown[];total:number}>("/api/v1/cases", {limit:1, status:"open"}),
      apiGet<{total:number}>("/api/v1/human-review", {limit:1, status:"pending"}),
      apiGet<{total:number}>("/api/v1/human-review", {limit:1, status:"in_progress"}),
      apiGet<{total:number}>("/api/v1/human-review", {limit:1, status:"escalated"}),
      // The Escalations board's own source (task routing), a different model
      // from human-review approvals and their own "escalated" status.
      canViewQueue ? getTaskBoard() : Promise.reject(),
      // ponytail: the 50 most recent items; "oldest waiting" is exact only
      // while fewer than 50 are open. Add a server-side oldest if queues grow.
      apiGet<{items: ReviewRow[]; total: number}>("/api/v1/human-review", {limit:50}),
      getWeeklyAppointmentCounts(),
      // A doctor sees their own day; everyone else the whole clinic's.
      getDayView(toDateInputValue(new Date()), user?.role === "doctor" ? user.id : undefined),
    ]);

  const total = (r: PromiseSettledResult<{ total: number }>) => (r.status === "fulfilled" ? r.value.total : 0);
  const anyReviewCount = [pendingRes, inProgressRes, reviewEscalatedRes].some(r => r.status === "fulfilled");
  const openReviews = reviewListRes.status === "fulfilled" ? reviewListRes.value.items.filter(t => OPEN_REVIEW.has(t.status)) : [];
  const escalatedTasks = boardRes.status === "fulfilled" ? boardRes.value.columns.escalated ?? [] : [];

  const attention: AttentionItem[] = [
    ...openReviews.map(t => ({
      id: t.id,
      href: `/review-queue?item=${t.id}`,
      title: t.contact_reason ?? t.case_title ?? t.patient_name ?? "Review item",
      kind: [KIND_LABEL[t.task_type] ?? t.task_type, t.patient_name].filter(Boolean).join(", "),
      urgency: t.status === "escalated" ? ("urgent" as const) : t.priority === "high" ? ("high" as const) : null,
      createdAt: t.created_at,
    })),
    ...escalatedTasks.map(t => ({
      id: t.id,
      href: `/escalations?task=${t.id}`,
      title: t.subject ?? "Escalated message",
      kind: ["Escalated", t.fromName].filter(Boolean).join(", "),
      urgency: t.priority === "urgent" ? ("urgent" as const) : ("high" as const),
      createdAt: t.createdAt,
    })),
  ].sort((a, b) => {
    const rank = (u: AttentionItem["urgency"]) => (u === "urgent" ? 0 : u === "high" ? 1 : 2);
    return rank(a.urgency) - rank(b.urgency) || a.createdAt.localeCompare(b.createdAt);
  });

  return {
    openCases: casesRes.status === "fulfilled" ? casesRes.value.total : null,
    awaitingApproval: anyReviewCount ? total(pendingRes) + total(inProgressRes) + total(reviewEscalatedRes) : null,
    escalations: boardRes.status === "fulfilled" ? boardRes.value.counts.escalated : null,
    oldestAwaiting: oldest(openReviews.map(t => t.created_at)),
    oldestEscalated: oldest(escalatedTasks.map(t => t.createdAt)),
    workflowByDay: weeklyRes.status === "fulfilled" ? weeklyRes.value : [],
    today: todayRes.status === "fulfilled" ? todayRes.value.appointments.filter(a => a.status !== "cancelled") : [],
    attention: attention.slice(0, 6),
  };
}

export async function listMessages(archived = false): Promise<Message[]> {
  const res = await apiGet<{ items: Message[]; total: number }>("/api/v1/inbox", { archived });
  return res.items;
}

// GET /inbox/{task_id} 404s unless the viewer sees it in their own inbox or
// can act on an open review item linked to it -- used both for the deep
// link from a review-queue item and the Inbox's own ?task= deep link.
export async function getInboxMessage(taskId: string): Promise<Message> {
  return apiGet<Message>(`/api/v1/inbox/${taskId}`);
}

// Rejects a held draft reply. Gated server-side by can_act on the linked
// review item, which is broader than can_approve (an operator may reject a
// clinical draft they may not approve) -- see human_review_service.can_act.
export async function rejectDraft(approvalId: string, notes: string): Promise<void> {
  await apiPost(`/api/v1/approvals/${approvalId}/reject`, { notes });
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

// Write reply (D14): sends the person's own text; answers with the updated message.
export async function sendManualReply(taskId: string, text: string): Promise<Message> {
  return apiPost<Message>(`/api/v1/inbox/${taskId}/reply`, { text });
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
