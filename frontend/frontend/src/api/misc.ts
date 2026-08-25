import { apiDelete, apiGet, apiPost } from "../lib/apiClient";
import type { DashboardSummary, Message } from "./types";
import { placeholderWorkflowByDay } from "./_placeholder";

const TASK_TYPE_LABEL: Record<string, string> = {
  triage_review: "HITL Approval",
  consent_review: "Consent Review",
  escalation_review: "Escalation Review",
  routing_review: "Routing Review",
};

export async function getDashboard(): Promise<DashboardSummary> {
  // Fetch real data in parallel, fall back gracefully
  const [intakeRes, auditRes, pendingRes, inProgressRes, escalatedRes, reviewListRes] =
    await Promise.allSettled([
      apiGet<{items:unknown[];total:number}>("/api/v1/intake?limit=1"),
      apiGet<{total:number}>("/api/v1/audit?limit=1"),
      apiGet<{total:number}>("/api/v1/human-review", {limit:1, status:"pending"}),
      apiGet<{total:number}>("/api/v1/human-review", {limit:1, status:"in_progress"}),
      apiGet<{total:number}>("/api/v1/human-review", {limit:1, status:"escalated"}),
      apiGet<{items:{id:string;case_id:string;task_type:string;status:string}[];total:number}>(
        "/api/v1/human-review", {limit:20}
      ),
    ]);

  const openCases = intakeRes.status==="fulfilled" ? intakeRes.value.total : 0;
  const auditEvents = auditRes.status==="fulfilled" ? auditRes.value.total : 0;
  const pending = pendingRes.status==="fulfilled" ? pendingRes.value.total : 0;
  const inProgress = inProgressRes.status==="fulfilled" ? inProgressRes.value.total : 0;
  const escalated = escalatedRes.status==="fulfilled" ? escalatedRes.value.total : 0;

  // Pending Reviews list: real human-review tasks, enriched with the real
  // patient name from each task's linked case (the task itself only carries
  // case_id, not a display name).
  let pendingReviews: DashboardSummary["pendingReviews"] = [];
  if (reviewListRes.status === "fulfilled") {
    const openTasks = reviewListRes.value.items
      .filter(t => t.status === "pending" || t.status === "in_progress")
      .slice(0, 4);

    pendingReviews = await Promise.all(
      openTasks.map(async (task) => {
        let name = "Unknown patient";
        try {
          const caseData = await apiGet<{ patient_name: string | null }>(
            `/api/v1/intake/${task.case_id}`
          );
          name = caseData.patient_name ?? "Unknown patient";
        } catch { /* keep fallback */ }
        return {
          id: task.id,
          name,
          kind: TASK_TYPE_LABEL[task.task_type] ?? task.task_type,
          isNew: task.status === "pending",
        };
      })
    );
  }

  return {
    openCases,
    awaitingApproval: pending + inProgress,
    escalations: escalated,
    auditEvents,
    workflowByDay: placeholderWorkflowByDay,
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
