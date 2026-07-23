import { apiGet, apiPost } from "../lib/apiClient";
import {
  placeholderMessages,
  placeholderWorkflowByDay,
} from "./_placeholder";
import type {
  DashboardSummary,
  Message,
  RagAnswer,
  RecordDocument,
} from "./types";

// ── Dashboard (design 3) ──────────────────────────────────────────────────
// The four tiles map to real counts. The weekly workflow chart and the
// "pending reviews" list have no dedicated backend, so those come from the
// placeholder source behind this adapter.
export async function getDashboard(): Promise<DashboardSummary> {
  const [intake, review, routing] = await Promise.all([
    apiGet<{ status_counts: Record<string, number> }>("/api/v1/intake/summary"),
    apiGet<{ open_counts: Record<string, number> }>("/api/v1/review-tasks/summary").catch(
      () => ({ open_counts: {} }),
    ),
    apiGet<{ queue_counts: Record<string, number> }>("/api/v1/routing/summary").catch(
      () => ({ queue_counts: {} }),
    ),
  ]);

  const counts = intake.status_counts ?? {};
  const openCases = Object.entries(counts)
    .filter(([k]) => !k.startsWith("routed") && k !== "escalated")
    .reduce((sum, [, v]) => sum + v, 0);
  const awaitingApproval = Object.values(review.open_counts ?? {}).reduce((s, v) => s + v, 0);
  const escalations = Object.entries(routing.queue_counts ?? {})
    .filter(([k]) => k.includes("escalation"))
    .reduce((s, [, v]) => s + v, 0);

  return {
    openCases,
    awaitingApproval,
    escalations,
    auditEvents: 0, // filled below where audit is readable; 0 if not permitted
    workflowByDay: placeholderWorkflowByDay,
    pendingReviews: [
      { id: "1", name: "Emily Zhang", kind: "Consent Review", isNew: true },
      { id: "2", name: "Marcus Williams", kind: "Treatment Auth", isNew: true },
      { id: "3", name: "Sarah Johnson", kind: "Medical Records", isNew: false },
      { id: "4", name: "David Chen", kind: "Insurance Claim", isNew: false },
    ],
  };
}

// ── Records / RAG (design 9) ──────────────────────────────────────────────
// The document browser list is placeholder (no documents backend). The "Open
// full record" / search action calls the real RAG query endpoint.
export const placeholderRecords: RecordDocument[] = [
  {
    id: "r1",
    title: "Discharge summary",
    type: "Clinical note",
    source: "Emergency Dept",
    date: "20 May 2026",
    pages: 3,
    confidentiality: "Standard",
  },
  {
    id: "r2",
    title: "Lab results - FBC",
    type: "Laboratory",
    source: "Pathology",
    date: "19 May 2026",
    pages: 1,
    confidentiality: "Standard",
  },
  {
    id: "r3",
    title: "Imaging - Chest X-ray",
    type: "Radiology",
    source: "Radiology",
    date: "19 May 2026",
    pages: 2,
    confidentiality: "Standard",
  },
  {
    id: "r4",
    title: "Medication chart",
    type: "Prescription",
    source: "Pharmacy",
    date: "18 May 2026",
    pages: 1,
    confidentiality: "Standard",
  },
  {
    id: "r5",
    title: "Admission notes",
    type: "Clinical note",
    source: "Ward 3B",
    date: "18 May 2026",
    pages: 4,
    confidentiality: "Standard",
  },
];

export async function ragQuery(input: {
  patient_id: string;
  question: string;
}): Promise<RagAnswer> {
  const res = await apiPost<{
    answer: string;
    refusal_source: "none" | "gate" | "llm";
    decision: string;
    citations: {
      chunk_id: string;
      doc_type: string;
      source_document_id: string;
      score: number;
      content: string;
    }[];
  }>("/api/v1/rag/query", input);
  return {
    answer: res.answer,
    refusalSource: res.refusal_source,
    decision: res.decision,
    citations: res.citations.map((c) => ({
      id: c.chunk_id,
      title: c.doc_type,
      type: c.doc_type,
      source: c.source_document_id,
      date: "",
      pages: null,
      confidentiality: "Standard",
    })),
  };
}

// ── Messages / Inbox (design 10) ──────────────────────────────────────────
// SEAM: no messaging backend. Served entirely from the placeholder source.
// Replace this body with real thread calls when a messaging service exists.
export async function listMessages(): Promise<Message[]> {
  return placeholderMessages;
}
