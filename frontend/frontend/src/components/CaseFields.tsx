import { useEffect, useId, useState } from "react";
import { Link } from "react-router-dom";
import { listEpisodes, moveToEpisode, NEW_CASE, type Episode } from "../api/episodes";
import { describeApiError } from "../lib/apiClient";
import { listDoctors } from "../api/doctors";
import { listPatients } from "../api/cases";
import type { Doctor, Message, Patient } from "../api/types";

const FIELD = "w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand";
const LABEL = "mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500";

// A patient's open cases plus "New case…" (M4). The value is a case id,
// NEW_CASE (with newTitle), or "" when optional and nothing is chosen.
export function CasePicker({
  patientId, value, onChange, newTitle, onNewTitle, optional = false, optionalLabel = "No case",
}: {
  patientId: string; value: string; onChange: (v: string) => void;
  newTitle: string; onNewTitle: (v: string) => void;
  optional?: boolean; optionalLabel?: string;
}) {
  const id = useId();
  const [cases, setCases] = useState<Episode[] | null>(null);

  useEffect(() => {
    let live = true;
    listEpisodes({ patientId, status: "open" })
      .then(items => {
        if (!live) return;
        setCases(items);
        // Default when nothing is chosen yet: the most recently active open case
        // (listed first, as the case suggestion falls back to), else a new one.
        if (!value) onChange(optional ? "" : items[0]?.id ?? NEW_CASE);
      })
      .catch(() => live && setCases([]));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload only when the patient changes
  }, [patientId]);

  return (
    <div>
      <label htmlFor={id} className={LABEL}>Case</label>
      <select id={id} value={value} onChange={e => onChange(e.target.value)} disabled={cases === null} className={FIELD}>
        {optional && <option value="">{optionalLabel}</option>}
        {(cases ?? []).map(c => <option key={c.id} value={c.id}>{c.title}</option>)}
        <option value={NEW_CASE}>New case…</option>
      </select>
      {value === NEW_CASE && (
        <input aria-label="New case title" value={newTitle} onChange={e => onNewTitle(e.target.value)}
          placeholder="What is the case about? e.g. Knee pain" className={`mt-2 ${FIELD}`} />
      )}
    </div>
  );
}

// A doctor dropdown. emptyLabel adds an empty choice ("No preference").
export function DoctorSelect({
  label, value, onChange, emptyLabel,
}: { label: string; value: string; onChange: (v: string) => void; emptyLabel?: string }) {
  const id = useId();
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  useEffect(() => { listDoctors().then(setDoctors).catch(() => setDoctors([])); }, []);
  return (
    <div>
      <label htmlFor={id} className={LABEL}>{label}</label>
      <select id={id} value={value} onChange={e => onChange(e.target.value)} className={FIELD}>
        {emptyLabel !== undefined && <option value="">{emptyLabel}</option>}
        {doctors.map(d => <option key={d.id} value={d.id}>{d.fullName}</option>)}
      </select>
    </div>
  );
}

// Find a patient by name or MRN. Shows the chosen one with a Change link.
export function PatientSearch({
  label = "Patient", selected, onSelect,
}: { label?: string; selected: Patient | null; onSelect: (p: Patient | null) => void }) {
  const id = useId();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Patient[]>([]);

  useEffect(() => {
    if (query.trim().length < 2) { setResults([]); return; }
    const t = setTimeout(() => {
      listPatients({ search: query, limit: 8 }).then(r => setResults(r.items)).catch(() => setResults([]));
    }, 250);
    return () => clearTimeout(t);
  }, [query]);

  return (
    <div>
      <label htmlFor={id} className={LABEL}>{label}</label>
      {selected ? (
        <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm">
          <span className="text-slate-900">{selected.name} <span className="text-slate-400">({selected.mrn})</span></span>
          <button type="button" onClick={() => { onSelect(null); setQuery(""); }} className="text-xs text-brand hover:underline">Change</button>
        </div>
      ) : (
        <div className="relative">
          <input id={id} value={query} onChange={e => setQuery(e.target.value)} placeholder="Search by patient name or MRN" className={FIELD} />
          {results.length > 0 && (
            <div className="absolute z-10 mt-1 w-full overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
              {results.map(p => (
                <button type="button" key={p.id} onClick={() => { onSelect(p); setResults([]); }}
                  className="block w-full px-3.5 py-2 text-left text-sm hover:bg-slate-50">
                  {p.name} <span className="text-slate-400">({p.mrn})</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// The inbox's case chip (M4): the case a message is in, and Change. A message
// with no confirmed patient (a voicemail, an unknown sender) asks staff to
// confirm who it is from before listing that patient's cases.
export function CaseChip({ message, onChanged }: { message: Message; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [confirmed, setConfirmed] = useState<Patient | null>(null);
  const [choice, setChoice] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const patientId = message.patientId ?? confirmed?.id ?? null;

  function reset() { setEditing(false); setConfirmed(null); setChoice(""); setTitle(""); setError(null); }

  async function save() {
    if (!patientId || !choice) return;
    setBusy(true); setError(null);
    try {
      await moveToEpisode({
        kind: "contact", itemId: message.caseId,
        targetEpisodeId: choice === NEW_CASE ? null : choice,
        newTitle: choice === NEW_CASE ? title || message.subject : undefined,
        patientId: message.patientId ? undefined : patientId,
      });
      reset();
      onChanged();
    } catch (err) {
      setError(describeApiError(err, "Could not change the case."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
      <div className="flex items-center gap-2">
        <span className="font-semibold text-slate-600">Case:</span>
        {message.episodeId
          ? <Link to={`/cases/${message.episodeId}`} className="font-medium text-brand hover:underline">{message.episodeTitle}</Link>
          : <span className="text-slate-500">No case</span>}
        {!editing && <button onClick={() => setEditing(true)} className="ml-auto text-brand hover:underline">Change</button>}
      </div>
      {editing && (
        <div className="mt-2 space-y-2">
          {!message.patientId && (
            <PatientSearch label="Confirm who this is from" selected={confirmed} onSelect={p => { setConfirmed(p); setChoice(""); }} />
          )}
          {patientId && (
            <CasePicker patientId={patientId} value={choice} onChange={setChoice} newTitle={title} onNewTitle={setTitle} />
          )}
          {error && <p className="text-red-600">{error}</p>}
          <div className="flex gap-2">
            <button onClick={save} disabled={busy || !patientId || !choice} className="rounded-lg bg-brand px-3 py-1.5 font-semibold text-white disabled:opacity-50">Save case</button>
            <button onClick={reset} className="text-slate-500">Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
