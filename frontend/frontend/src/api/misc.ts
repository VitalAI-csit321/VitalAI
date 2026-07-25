import { apiGet, apiPost } from "../lib/apiClient";
import { placeholderMessages, placeholderWorkflowByDay } from "./_placeholder";
import type { DashboardSummary, Message, RagAnswer, RecordDocument } from "./types";

export async function getDashboard(): Promise<DashboardSummary> {
  const [intake, tasks] = await Promise.all([
    apiGet<{ items: unknown[]; total: number }>("/api/v1/intake", { limit: 1 }).catch(() => ({ items: [], total: 0 })),
    apiGet<{ counts: { pending: number; in_progress: number; escalated: number; completed: number } }>("/api/v1/tasks/board").catch(() => ({ counts: { pending: 0, in_progress: 0, escalated: 0, completed: 0 } })),
  ]);

  return {
    openCases: intake.total,
    awaitingApproval: (tasks.counts.pending ?? 0) + (tasks.counts.in_progress ?? 0),
    escalations: tasks.counts.escalated ?? 0,
    auditEvents: 0,
    workflowByDay: placeholderWorkflowByDay,
    pendingReviews: [
      { id: "1", name: "Emily Zhang", kind: "Consent Review", isNew: true },
      { id: "2", name: "Marcus Williams", kind: "Treatment Auth", isNew: true },
      { id: "3", name: "Sarah Johnson", kind: "Medical Records", isNew: false },
      { id: "4", name: "David Chen", kind: "Insurance Claim", isNew: false },
    ],
  };
}

export const placeholderRecords: RecordDocument[] = [
  { id: "r1", title: "Discharge summary", type: "Clinical note", source: "Emergency Dept", date: "20 May 2026", pages: 3, confidentiality: "Standard" },
  { id: "r2", title: "Lab results - FBC", type: "Laboratory", source: "Pathology", date: "19 May 2026", pages: 1, confidentiality: "Standard" },
  { id: "r3", title: "Imaging - Chest X-ray", type: "Radiology", source: "Radiology", date: "19 May 2026", pages: 2, confidentiality: "Standard" },
  { id: "r4", title: "Medication chart", type: "Prescription", source: "Pharmacy", date: "18 May 2026", pages: 1, confidentiality: "Standard" },
  { id: "r5", title: "Admission notes", type: "Clinical note", source: "Ward 3B", date: "18 May 2026", pages: 4, confidentiality: "Standard" },
];

export async function ragQuery(input: { patient_id: string; question: string }): Promise<RagAnswer> {
  const res = await apiPost<{ answer: string; refusal_source: "none" | "gate" | "llm"; decision: string; citations: { chunk_id: string; doc_type: string; source_document_id: string; score: number; content: string }[] }>("/api/v1/rag/query", input);
  return {
    answer: res.answer, refusalSource: res.refusal_source, decision: res.decision,
    citations: res.citations.map(c => ({ id: c.chunk_id, title: c.doc_type, type: c.doc_type, source: c.source_document_id, date: "", pages: null, confidentiality: "Standard" })),
  };
}

export async function listMessages(): Promise<Message[]> {
  return placeholderMessages;
}
