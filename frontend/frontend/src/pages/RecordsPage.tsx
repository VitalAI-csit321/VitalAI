import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { listClinicalDocuments, listIndexedDocuments, ragQuery } from "../api/records";
import { listPatients } from "../api/cases";
import type { ClinicalDocument, IndexedDocument, Patient, RagAnswer } from "../api/types";
import { Spinner } from "../components/ui";

interface ChatTurn { question: string; answer: RagAnswer | null; error: string | null; loading: boolean; }

const SOURCE_OPTIONS = ["Emergency Dept", "Pathology", "Radiology", "Pharmacy", "Ward 3B"];
const DATE_RANGE_OPTIONS = ["Last 7 days", "Last 30 days", "Last 90 days", "All time"];
const TYPE_OPTIONS = [
  "consultation_note", "pathology_report", "prescription", "referral_letter",
  "specialist_letter", "hospital_discharge_summary", "external_imaging_report",
  "care_plan", "registration_form", "appointment_history", "consent_record",
];

function buildFilteredQuestion(question: string, filters: { source: string; dateRange: string; type: string }): string {
  const constraints: string[] = [];
  if (filters.source) constraints.push(`Source: ${filters.source}`);
  if (filters.dateRange) constraints.push(`Date range: ${filters.dateRange}`);
  if (filters.type) constraints.push(`Type: ${filters.type}`);
  return constraints.length ? `[${constraints.join(". ")}] ${question}` : question;
}

export function RecordsPage() {
  const [patientSearch, setPatientSearch] = useState("");
  const [patientResults, setPatientResults] = useState<Patient[]>([]);
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);
  const [documents, setDocuments] = useState<ClinicalDocument[]>([]);
  const [indexed, setIndexed] = useState<IndexedDocument[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [docsError, setDocsError] = useState<string | null>(null);

  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [filterOpen, setFilterOpen] = useState(false);
  const [source, setSource] = useState("");
  const [dateRange, setDateRange] = useState("");
  const [docType, setDocType] = useState("");
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (patientSearch.trim().length < 2) { setPatientResults([]); return; }
    const handle = setTimeout(() => {
      listPatients({ search: patientSearch, limit: 8 }).then(r => setPatientResults(r.items)).catch(() => {});
    }, 250);
    return () => clearTimeout(handle);
  }, [patientSearch]);

  useEffect(() => {
    if (!selectedPatient) { setDocuments([]); setIndexed([]); return; }
    setDocsLoading(true);
    setDocsError(null);
    // Two stores, deliberately: clinical_documents holds files uploaded through
    // the app, /rag/documents holds everything the retriever can actually cite
    // (the offline-ingested corpus has no uploads row). Listing only the first
    // showed "no documents" for patients the RAG answers about happily.
    Promise.all([listClinicalDocuments(selectedPatient.id), listIndexedDocuments(selectedPatient.id)])
      .then(([docs, idx]) => { setDocuments(docs); setIndexed(idx); })
      .catch(() => setDocsError("Could not load documents for this patient."))
      .finally(() => setDocsLoading(false));
  }, [selectedPatient]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  // Chunks carry only a source document id; corpus-ingested chunks have no
  // ClinicalDocument row at all, so fall back to the doc type in the citation.
  const documentNames = new Map(documents.map(d => [d.id, d.filename]));

  const uploadedIds = new Set(documents.map(d => d.id));
  const panelDocs = [
    ...documents.map(d => ({
      id: d.id,
      title: d.filename,
      subtitle: `${d.docType.replace(/_/g, " ")} • ${new Date(d.createdAt).toLocaleDateString("en-GB")}`,
      warning: d.ingestedAt ? null : "Not yet ingested",
    })),
    ...indexed.filter(i => !uploadedIds.has(i.sourceDocumentId)).map(i => ({
      id: i.sourceDocumentId,
      title: i.docType.replace(/_/g, " "),
      subtitle: `${i.chunkCount} indexed passage${i.chunkCount === 1 ? "" : "s"} • ${new Date(i.indexedAt).toLocaleDateString("en-GB")}`,
      warning: null,
    })),
  ];

  async function handleSearch() {
    if (!selectedPatient || !question.trim()) return;
    const q = question.trim();
    setQuestion("");
    const index = turns.length;
    setTurns(t => [...t, { question: q, answer: null, error: null, loading: true }]);

    try {
      const answer = await ragQuery({
        patient_id: selectedPatient.id,
        question: buildFilteredQuestion(q, { source, dateRange, type: docType }),
      });
      setTurns(t => t.map((turn, i) => i === index ? { ...turn, answer, loading: false } : turn));
    } catch {
      setTurns(t => t.map((turn, i) =>
        i === index ? { ...turn, error: "Could not get an answer. You may not have access to this patient's records.", loading: false } : turn
      ));
    }
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-slate-900">Record and information retrieval</h1>

      <div className="mt-4 relative max-w-md">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          value={selectedPatient ? selectedPatient.name : patientSearch}
          onChange={e => { setPatientSearch(e.target.value); setSelectedPatient(null); }}
          placeholder="Search for a patient by name or MRN..."
          className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm outline-none focus:border-brand"
        />
        {!selectedPatient && patientResults.length > 0 && (
          <div className="absolute z-10 mt-1 w-full rounded-lg border border-slate-200 bg-white shadow-lg">
            {patientResults.map(p => (
              <button
                key={p.id}
                onClick={() => { setSelectedPatient(p); setPatientResults([]); }}
                className="block w-full px-3 py-2 text-left text-sm hover:bg-slate-50"
              >
                <span className="font-medium text-slate-900">{p.name}</span>
                <span className="ml-2 text-xs text-slate-500 font-mono">{p.mrn}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {!selectedPatient ? (
        <p className="mt-6 text-sm text-slate-500">Select a patient to view their documents and ask questions.</p>
      ) : (
        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1fr_2fr]">
          {/* Left: document list */}
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-base font-semibold text-slate-900">Documents</h2>
            <p className="mt-1 text-xs text-slate-500">{panelDocs.length} for {selectedPatient.name}</p>
            <div className="mt-4 space-y-2">
              {docsLoading ? <Spinner /> : docsError ? (
                <p className="text-sm text-red-600">{docsError}</p>
              ) : panelDocs.length === 0 ? (
                <p className="text-sm text-slate-500">No documents on file for this patient.</p>
              ) : panelDocs.map(doc => (
                <div key={doc.id} className="rounded-lg border border-transparent p-3 hover:bg-slate-50">
                  <div className="text-sm font-semibold text-slate-900 capitalize">{doc.title}</div>
                  <div className="mt-0.5 text-xs text-slate-500 capitalize">{doc.subtitle}</div>
                  {doc.warning && <div className="mt-0.5 text-xs text-amber-600">{doc.warning}</div>}
                </div>
              ))}
            </div>
          </div>

          {/* Right: chat search */}
          <div className="rounded-xl border border-slate-200 bg-white p-5 flex flex-col min-h-[28rem]">
            <div className="flex-1 space-y-4 overflow-y-auto">
              {turns.length === 0 && <p className="text-sm text-slate-500">Ask a question about this patient's records.</p>}
              {turns.map((turn, i) => (
                <div key={i} className="space-y-2">
                  <div className="ml-auto max-w-[80%] rounded-lg bg-brand px-3 py-2 text-sm text-white">{turn.question}</div>
                  {turn.loading ? (
                    <Spinner />
                  ) : turn.error ? (
                    <p className="text-sm text-red-600">{turn.error}</p>
                  ) : turn.answer ? (
                    <div className="max-w-[90%] rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-800">
                      <p>{turn.answer.answer}</p>
                      {turn.answer.citations.length > 0 && (
                        <div className="mt-2 space-y-1 border-t border-slate-200 pt-2">
                          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Sources</p>
                          {turn.answer.citations.map(c => (
                            <div key={c.chunkId} className="flex items-baseline justify-between gap-3 text-xs text-slate-500">
                              <span className="truncate capitalize">
                                {documentNames.get(c.sourceDocumentId) ?? c.docType.replace(/_/g, " ")}
                              </span>
                              <span className="shrink-0 tabular-nums" title="Retrieval confidence (cosine similarity)">
                                {Math.round(c.score * 100)}%
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : null}
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>

            <div className="mt-4 flex gap-2">
              <input
                value={question}
                onChange={e => setQuestion(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") handleSearch(); }}
                placeholder="Ask a question about this patient's records..."
                className="flex-1 rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-brand"
              />
              <div className="relative">
                <button
                  onClick={() => setFilterOpen(o => !o)}
                  className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  Filters{(source || dateRange || docType) ? " •" : ""}
                </button>
                {filterOpen && (
                  <div className="absolute right-0 z-10 mt-1 w-64 space-y-3 rounded-lg border border-slate-200 bg-white p-4 shadow-lg">
                    <div>
                      <label className="block text-xs font-medium text-slate-500 uppercase tracking-wide">Source</label>
                      <select value={source} onChange={e => setSource(e.target.value)} className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm">
                        <option value="">Any</option>
                        {SOURCE_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-500 uppercase tracking-wide">Date range</label>
                      <select value={dateRange} onChange={e => setDateRange(e.target.value)} className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm">
                        <option value="">Any</option>
                        {DATE_RANGE_OPTIONS.map(d => <option key={d} value={d}>{d}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-500 uppercase tracking-wide">Type</label>
                      <select value={docType} onChange={e => setDocType(e.target.value)} className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm capitalize">
                        <option value="">Any</option>
                        {TYPE_OPTIONS.map(t => <option key={t} value={t} className="capitalize">{t.replace(/_/g, " ")}</option>)}
                      </select>
                    </div>
                  </div>
                )}
              </div>
              <button
                onClick={handleSearch}
                disabled={!question.trim()}
                className="rounded-lg bg-brand px-5 py-2.5 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50"
              >
                Search
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
