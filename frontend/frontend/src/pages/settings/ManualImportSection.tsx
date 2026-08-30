import { useEffect, useState } from "react";
import { listPatients } from "../../api/cases";
import { uploadClinicalDocument } from "../../api/records";
import type { ClinicalDocType, ClinicalDocument, Patient } from "../../api/types";
import { ApiError, describeApiError } from "../../lib/apiClient";
import { Spinner } from "../../components/ui";

const DOC_TYPES: { value: ClinicalDocType; label: string }[] = [
  { value: "consultation", label: "Consultation note" },
  { value: "pathology_report", label: "Pathology report" },
  { value: "prescription", label: "Prescription" },
];

// Mirrors MAX_UPLOAD_SIZE_BYTES in backend/app/services/clinical_document_service.py.
// Checked client-side only to fail fast; the backend remains the real limit.
const MAX_BYTES = 20 * 1024 * 1024;

// Only the statuses where we can say something more useful than the backend
// does. Everything else falls through to describeApiError, which surfaces the
// backend's own detail rather than burying it under a canned string.
function uploadErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return "You do not have permission to upload clinical documents.";
    if (err.status === 413) return "That file is larger than the 20 MB limit.";
    if (err.status === 415) return "Only PDF files are accepted.";
    if (err.status === 422) return "No text could be read from that PDF. Scanned images without a text layer cannot be ingested.";
  }
  return describeApiError(err, "Upload failed. Check that the backend is running and try again.");
}

export function ManualImportSection() {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [patientsLoading, setPatientsLoading] = useState(true);
  const [patientSearch, setPatientSearch] = useState("");
  const [patientId, setPatientId] = useState("");
  const [docType, setDocType] = useState<ClinicalDocType>("consultation");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState<ClinicalDocument[]>([]);

  // The patients endpoint caps limit at 100 (backend/app/routes/patients.py:36)
  // and the demo database holds more patients than that, so the list is
  // server-side searched rather than fetched whole.
  useEffect(() => {
    let active = true;
    setPatientsLoading(true);
    listPatients({ limit: 100, search: patientSearch || undefined })
      .then(res => { if (active) setPatients(res.items); })
      .catch(() => { if (active) setError("Could not load the patient list."); })
      .finally(() => { if (active) setPatientsLoading(false); });
    return () => { active = false; };
  }, [patientSearch]);

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0] ?? null;
    setError(null);
    if (picked && picked.size > MAX_BYTES) {
      setError("That file is larger than the 20 MB limit.");
      setFile(null);
      return;
    }
    setFile(picked);
  }

  async function onUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!patientId || !file) return;
    const form = e.target as HTMLFormElement;
    setUploading(true);
    setError(null);
    try {
      const doc = await uploadClinicalDocument({ patientId, docType, file });
      setUploaded(prev => [doc, ...prev]);
      setFile(null);
      form.reset();
    } catch (err) {
      setError(uploadErrorMessage(err));
    } finally {
      setUploading(false);
    }
  }

  return (
    <div>
      <h2 className="text-base font-semibold text-slate-900">Manual import</h2>
      <p className="mt-1 text-sm text-slate-500">
        Upload a clinical PDF for a patient, then ingest it so the assistant can cite it when answering questions.
      </p>

      <form onSubmit={onUpload} className="mt-5 space-y-4 rounded-xl border border-slate-200 p-5">
        <div>
          <label className="block text-xs font-bold text-brand uppercase tracking-wide mb-1.5">Patient</label>
          <input type="search" value={patientSearch} onChange={e => setPatientSearch(e.target.value)}
            placeholder="Search by name to narrow the list"
            className="mb-2 w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
          {patientsLoading ? <Spinner label="Loading patients" /> : (
            <select value={patientId} onChange={e => setPatientId(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand">
              <option value="">Select a patient</option>
              {patients.map(p => <option key={p.id} value={p.id}>{p.name} ({p.mrn})</option>)}
            </select>
          )}
          {patients.length === 100 && (
            <p className="mt-1 text-xs text-slate-500">Showing the first 100 matches. Search to narrow.</p>
          )}
        </div>

        <div>
          <label className="block text-xs font-bold text-brand uppercase tracking-wide mb-1.5">Document type</label>
          <select value={docType} onChange={e => setDocType(e.target.value as ClinicalDocType)}
            className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand">
            {DOC_TYPES.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
          </select>
        </div>

        <div>
          <label className="block text-xs font-bold text-brand uppercase tracking-wide mb-1.5">File</label>
          <input type="file" accept="application/pdf" onChange={onFileChange}
            className="w-full text-sm text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-4 file:py-2 file:text-sm file:font-medium file:text-slate-700 hover:file:bg-slate-200" />
          <p className="mt-1 text-xs text-slate-500">PDF only, up to 20 MB. The PDF must contain selectable text, not just scanned images.</p>
        </div>

        {error && <p className="rounded-lg bg-red-50 px-3.5 py-2.5 text-sm text-red-700">{error}</p>}

        <button type="submit" disabled={!patientId || !file || uploading}
          className="rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-40 disabled:cursor-not-allowed">
          {uploading ? "Uploading..." : "Upload document"}
        </button>
      </form>

      {uploaded.length > 0 && (
        <p className="mt-4 text-sm text-slate-500">{uploaded.length} document(s) uploaded this session.</p>
      )}
    </div>
  );
}
