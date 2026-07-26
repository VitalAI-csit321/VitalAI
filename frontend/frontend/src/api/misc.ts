import { apiGet } from "../lib/apiClient";
import type { DashboardSummary, Message, RecordDocument } from "./types";
import { placeholderMessages, placeholderWorkflowByDay } from "./_placeholder";

export const placeholderRecords: RecordDocument[] = [
  { id:"r1", title:"Discharge summary", type:"Clinical note", source:"Emergency Dept", date:"20 May 2026", pages:3, confidentiality:"Standard" },
  { id:"r2", title:"Lab results - FBC", type:"Laboratory", source:"Pathology", date:"19 May 2026", pages:1, confidentiality:"Standard" },
  { id:"r3", title:"Imaging - Chest X-ray", type:"Radiology", source:"Radiology", date:"19 May 2026", pages:2, confidentiality:"Standard" },
  { id:"r4", title:"Medication chart", type:"Prescription", source:"Pharmacy", date:"18 May 2026", pages:1, confidentiality:"Standard" },
  { id:"r5", title:"Admission notes", type:"Clinical note", source:"Ward 3B", date:"18 May 2026", pages:4, confidentiality:"Standard" },
];

// Real task_type display labels
const TASK_TYPE_LABEL: Record<string, string> = {
  triage_review: "HITL Approval",
  consent_review: "Consent Review",
  escalation_review: "Escalation Review",
  routing_review: "Routing Review",
};

export async function getDashboard(): Promise<DashboardSummary> {
  // Fetch all real data in parallel
  const [intakeRes, taskBoardRes, reviewRes] = await Promise.allSettled([
    apiGet<{ id: string; total?: number }[]>("/api/v1/intake?limit=1"),
    apiGet<{ counts: { pending: number; in_progress: number; escalated: number; completed: number } }>("/api/v1/tasks/board"),
    apiGet<{ items: { id: string; case_id: string; task_type: string; status: string; created_at: string }[]; total: number; pending: number }>("/api/v1/review-tasks?limit=10"),
  ]);

  // Open cases count — from intake list total
  let openCases = 0;
  if (intakeRes.status === "fulfilled") {
    // Try to get total from a summary or count all intake
    try {
      const all = await apiGet<{ id: string }[]>("/api/v1/intake?limit=100");
      openCases = Array.isArray(all) ? all.length : 0;
    } catch { openCases = 0; }
  }

  // Escalations from task board
  const counts = taskBoardRes.status === "fulfilled"
    ? taskBoardRes.value.counts
    : { pending: 0, in_progress: 0, escalated: 0, completed: 0 };

  // Review tasks — real data for pending reviews list
  let pendingReviews: DashboardSummary["pendingReviews"] = [];
  let awaitingApproval = 0;

  if (reviewRes.status === "fulfilled") {
    const reviewData = reviewRes.value;
    awaitingApproval = reviewData.pending ?? reviewData.total ?? 0;

    // For each pending/in_progress task, fetch the linked case to get the real patient name
    const pendingTasks = reviewData.items.filter(t =>
      t.status === "pending" || t.status === "in_progress"
    ).slice(0, 4);

    pendingReviews = await Promise.all(
      pendingTasks.map(async (task) => {
        let patientName = "Unknown patient";
        try {
          const caseData = await apiGet<{ patient_name: string }>(`/api/v1/intake/${task.case_id}`);
          patientName = caseData.patient_name ?? "Unknown patient";
        } catch { /* use fallback */ }

        return {
          id: task.id,
          name: patientName,
          kind: TASK_TYPE_LABEL[task.task_type] ?? task.task_type,
          isNew: task.status === "pending",
        };
      })
    );
  }

  return {
    openCases,
    awaitingApproval,
    escalations: counts.escalated ?? 0,
    auditEvents: 0, // no global audit count endpoint yet
    workflowByDay: placeholderWorkflowByDay,
    pendingReviews,
  };
}

export async function listMessages(): Promise<Message[]> {
  return placeholderMessages;
}

export interface RagAnswer {
  answer: string;
  refusalSource: "none" | "gate" | "llm";
  decision: string;
  citations: RecordDocument[];
}

export async function ragQuery(input: { patient_id: string; question: string }): Promise<RagAnswer> {
  const res = await apiGet<{
    answer: string; refusal_source: "none" | "gate" | "llm"; decision: string;
    citations: { chunk_id: string; doc_type: string; source_document_id: string; score: number; content: string }[];
  }>("/api/v1/rag/query", input as unknown as Record<string, unknown>);
  return {
    answer: res.answer, refusalSource: res.refusal_source, decision: res.decision,
    citations: res.citations.map(c => ({
      id: c.chunk_id, title: c.doc_type, type: c.doc_type,
      source: c.source_document_id, date: "", pages: null, confidentiality: "Standard",
    })),
  };
}
