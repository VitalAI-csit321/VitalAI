import { apiGet, apiPost } from "../lib/apiClient";
import type { ClinicalDocument, RagAnswer } from "./types";

interface RawClinicalDocument {
  id: string; patient_id: string; doc_type: string; filename: string;
  content_type: string; size_bytes: number; uploaded_by: string;
  ingested_at: string | null; created_at: string;
}

function toClinicalDocument(r: RawClinicalDocument): ClinicalDocument {
  return {
    id: r.id, patientId: r.patient_id, docType: r.doc_type, filename: r.filename,
    createdAt: r.created_at, ingestedAt: r.ingested_at,
  };
}

export async function listClinicalDocuments(patientId: string): Promise<ClinicalDocument[]> {
  const raw = await apiGet<RawClinicalDocument[]>("/api/v1/clinical-documents", { patient_id: patientId });
  return raw.map(toClinicalDocument);
}

interface RawChunk {
  chunk_id: string; source_document_id: string; doc_type: string; content: string; score: number;
}

interface RawAnswerResult {
  answer: string;
  refusal_source: "none" | "gate" | "llm";
  gate_outcome: { decision: string; chunks: RawChunk[] };
}

export async function ragQuery(input: { patient_id: string; question: string }): Promise<RagAnswer> {
  const res = await apiPost<RawAnswerResult>("/api/v1/rag/query", input);
  return {
    answer: res.answer,
    refusalSource: res.refusal_source,
    decision: res.gate_outcome.decision,
    citations: res.gate_outcome.chunks.map(c => ({
      chunkId: c.chunk_id, sourceDocumentId: c.source_document_id,
      docType: c.doc_type, content: c.content, score: c.score,
    })),
  };
}
