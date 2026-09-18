import { apiGet, apiGetBlob, apiPost, apiPostForm } from "../lib/apiClient";
import type { ClinicalDocType, ClinicalDocument, IndexedDocument, IngestResult, RagAnswer } from "./types";

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

interface RawIndexedDocument {
  source_document_id: string; doc_type: string; chunk_count: number; indexed_at: string;
}

export async function listIndexedDocuments(patientId: string): Promise<IndexedDocument[]> {
  const raw = await apiGet<RawIndexedDocument[]>("/api/v1/rag/documents", { patient_id: patientId });
  return raw.map(r => ({
    sourceDocumentId: r.source_document_id, docType: r.doc_type,
    chunkCount: r.chunk_count, indexedAt: r.indexed_at,
  }));
}

// The backend accepts PDF only, 20 MB max, and exactly three doc types.
// See backend/app/services/clinical_document_service.py.
export async function uploadClinicalDocument(input: {
  patientId: string;
  docType: ClinicalDocType;
  file: File;
}): Promise<ClinicalDocument> {
  const form = new FormData();
  form.set("patient_id", input.patientId);
  form.set("doc_type", input.docType);
  form.set("file", input.file);
  return toClinicalDocument(await apiPostForm<RawClinicalDocument>("/api/v1/clinical-documents", form));
}

// Opens the document's PDF in a new tab. Backend still enforces VIEW_CLINICAL
// + per-patient scoping regardless of who calls this; the doctor-only gate on
// showing this action at all is a frontend UX restriction, not the security
// boundary.
export async function openClinicalDocument(documentId: string): Promise<void> {
  const blob = await apiGetBlob(`/api/v1/clinical-documents/${documentId}/file`);
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

interface RawIngestResult {
  document_id: string; chunk_count: number; ingested_at: string;
}

export async function ingestClinicalDocument(documentId: string): Promise<IngestResult> {
  const r = await apiPost<RawIngestResult>(`/api/v1/clinical-documents/${documentId}/ingest`);
  return { documentId: r.document_id, chunkCount: r.chunk_count, ingestedAt: r.ingested_at };
}

interface RawChunk {
  chunk_id: string; source_document_id: string; doc_type: string; content: string; score: number;
}

interface RawAnswerResult {
  answer: string;
  refusal_source: "none" | "gate" | "llm";
  gate_outcome: { decision: string; chunks: RawChunk[] };
  citations: RawChunk[];
}

export async function ragQuery(input: { patient_id: string; question: string }): Promise<RagAnswer> {
  const res = await apiPost<RawAnswerResult>("/api/v1/rag/query", input);
  return {
    answer: res.answer,
    refusalSource: res.refusal_source,
    decision: res.gate_outcome.decision,
    // One entry per source document, best-scoring chunk wins; gate_outcome.chunks
    // is the wider retrieved set and is not what the answer was grounded in.
    citations: [...new Map(
      res.citations
        .slice()
        .sort((a, b) => b.score - a.score)
        .map(c => [c.source_document_id, {
          chunkId: c.chunk_id, sourceDocumentId: c.source_document_id,
          docType: c.doc_type, content: c.content, score: c.score,
        }] as const),
    ).values()],
  };
}
