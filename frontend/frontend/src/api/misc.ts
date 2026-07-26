import { apiGet, apiPost } from "../lib/apiClient";
import type { DashboardSummary, Message } from "./types";
import { placeholderWorkflowByDay } from "./_placeholder";

export async function getDashboard(): Promise<DashboardSummary> {
  // Fetch real data in parallel, fall back gracefully
  const [intakeRes, auditRes, pendingRes, inProgressRes, escalatedRes] = await Promise.allSettled([
    apiGet<{items:unknown[];total:number}>("/api/v1/intake?limit=1"),
    apiGet<{total:number}>("/api/v1/audit?limit=1"),
    apiGet<{total:number}>("/api/v1/human-review", {limit:1, status:"pending"}),
    apiGet<{total:number}>("/api/v1/human-review", {limit:1, status:"in_progress"}),
    apiGet<{total:number}>("/api/v1/human-review", {limit:1, status:"escalated"}),
  ]);

  const openCases = intakeRes.status==="fulfilled" ? intakeRes.value.total : 0;
  const auditEvents = auditRes.status==="fulfilled" ? auditRes.value.total : 0;
  const pending = pendingRes.status==="fulfilled" ? pendingRes.value.total : 0;
  const inProgress = inProgressRes.status==="fulfilled" ? inProgressRes.value.total : 0;
  const escalated = escalatedRes.status==="fulfilled" ? escalatedRes.value.total : 0;

  return {
    openCases,
    awaitingApproval: pending + inProgress,
    escalations: escalated,
    auditEvents,
    workflowByDay: placeholderWorkflowByDay,
    pendingReviews: [
      {id:"1",name:"Emily Zhang",kind:"Consent Review",isNew:true},
      {id:"2",name:"Marcus Williams",kind:"Treatment Auth",isNew:true},
      {id:"3",name:"Sarah Johnson",kind:"Medical Records",isNew:false},
      {id:"4",name:"David Chen",kind:"Insurance Claim",isNew:false},
    ],
  };
}

export async function listMessages(): Promise<Message[]> {
  const res = await apiGet<{ items: Message[]; total: number }>("/api/v1/inbox");
  return res.items;
}

// Approves a pending draft reply (email.draft_reply approval), marking it sent.
// editedDraft/emailId/taskId let the operator send a corrected version of the
// AI draft instead of the original -- resolved_payload fully replaces the
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
