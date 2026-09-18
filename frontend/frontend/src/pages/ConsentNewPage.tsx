import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { listPatients, findLatestCaseForPatient, createCase } from "../api/cases";
import { CONSENT_TYPES } from "../api/consent";
import type { Patient } from "../api/types";
import { Spinner } from "../components/ui";

export function ConsentNewPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Patient[]>([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<Patient | null>(null);
  const [consentType, setConsentType] = useState(CONSENT_TYPES[0].value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function search(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setSearching(true); setError(null);
    try {
      const r = await listPatients({ search: query, limit: 10 });
      setResults(r.items);
    } catch {
      setError("Could not search patients. Please try again.");
    } finally {
      setSearching(false);
    }
  }

  async function continueToCapture() {
    if (!selected) return;
    setBusy(true); setError(null);
    try {
      const latest = await findLatestCaseForPatient(selected.id);
      const caseId = latest
        ? latest.id
        : (await createCase({
            patient_id: selected.id,
            patient_name: selected.name,
            contact_reason: "Consent capture",
            contact_channel: "in_person",
          })).id;
      navigate(`/consent/capture?case=${caseId}&type=${consentType}`);
    } catch {
      setError("Could not start consent capture for this patient. Please try again.");
      setBusy(false);
    }
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-slate-900">New consent</h1>
      <p className="mt-1 text-sm text-slate-500">Search for a patient by name or MRN to record a consent under their record.</p>

      <form onSubmit={search} className="mt-6 flex max-w-lg gap-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name or MRN..."
          className="flex-1 rounded-lg border border-slate-200 px-4 py-2 text-sm focus:border-brand focus:outline-none"
        />
        <button type="submit" disabled={searching} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50">
          {searching ? "Searching…" : "Search"}
        </button>
      </form>

      {searching ? (
        <div className="mt-6"><Spinner /></div>
      ) : results.length > 0 && (
        <div className="mt-6 max-w-lg overflow-hidden rounded-xl border border-slate-200 bg-white">
          {results.map((p) => (
            <button
              key={p.id}
              onClick={() => setSelected(p)}
              className={`flex w-full items-center justify-between border-b border-slate-100 px-4 py-3 text-left text-sm last:border-0 hover:bg-slate-50 ${selected?.id === p.id ? "bg-brand/5" : ""}`}
            >
              <span className="font-medium text-slate-900">{p.name}</span>
              <span className="font-mono text-slate-500">{p.mrn}</span>
            </button>
          ))}
        </div>
      )}

      {selected && (
        <div className="mt-6 max-w-lg rounded-xl border border-slate-200 bg-white p-6">
          <p className="text-sm text-slate-700">
            Recording consent for <span className="font-semibold text-slate-900">{selected.name}</span> ({selected.mrn})
          </p>
          <label className="mt-4 block text-xs font-semibold uppercase tracking-wide text-slate-500">
            Consent type
            <select
              value={consentType}
              onChange={(e) => setConsentType(e.target.value)}
              className="mt-1 block w-full rounded-lg border border-slate-200 px-3 py-2 text-sm font-normal normal-case text-slate-900 focus:border-brand focus:outline-none"
            >
              {CONSENT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </label>
          <button
            onClick={continueToCapture}
            disabled={busy}
            className="mt-4 rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50"
          >
            {busy ? "Starting…" : "Continue to capture"}
          </button>
        </div>
      )}

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
    </div>
  );
}
