import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  closeEpisode, getEpisode, listEpisodes, moveToEpisode, NEW_CASE, reopenEpisode, updateEpisode,
  type Episode, type EpisodeDetail, type TimelineEntry,
} from "../api/episodes";
import { describeApiError } from "../lib/apiClient";
import { DoctorSelect } from "../components/CaseFields";
import { Spinner, StatusBadge } from "../components/ui";

const KIND_LABEL: Record<TimelineEntry["kind"], string> = {
  contact: "Contact", appointment: "Appointment", consent: "Consent", review: "Review Queue",
};
const btn = "rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50";

function when(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

function openLink(e: TimelineEntry): string | null {
  if (e.kind === "contact") return e.inboxTaskId ? `/inbox?task=${e.inboxTaskId}` : `/contacts/${e.id}`;
  if (e.kind === "appointment") return `/calendar/${e.id}`;
  if (e.kind === "consent") return e.contactId ? `/contacts/${e.contactId}` : null;
  return "/review-queue";
}

// A case: one clinical problem, its contacts, bookings and consents (M4).
export function CasePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [episode, setEpisode] = useState<EpisodeDetail | null>(null);
  const [others, setOthers] = useState<Episode[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editingTitle, setEditingTitle] = useState<string | null>(null);
  const [doctorChoice, setDoctorChoice] = useState("");
  const [closeNote, setCloseNote] = useState<string | null>(null);
  const [moving, setMoving] = useState<{ entry: TimelineEntry; target: string; title: string } | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const e = await getEpisode(id);
      setEpisode(e);
      setDoctorChoice(e.doctorId ?? "");
      setOthers((await listEpisodes({ patientId: e.patientId, status: "open" })).filter(o => o.id !== e.id));
    } catch (err) {
      setError(describeApiError(err, "Could not load this case."));
    }
  }, [id]);

  useEffect(() => { void load(); }, [load]);

  async function act(action: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await action(); await load(); } catch (err) { setError(describeApiError(err, "That did not work.")); } finally { setBusy(false); }
  }

  if (!episode) {
    return <div className="p-6">{error ? <p className="text-sm text-red-600">{error}</p> : <Spinner label="Loading case..." />}</div>;
  }
  const open = episode.status === "open";
  const withCase = `patientId=${episode.patientId}&episodeId=${episode.id}`;

  return (
    <div className="p-6">
      <button onClick={() => navigate(-1)} className="text-sm text-slate-500 hover:text-slate-700">← Back</button>

      <div className="mt-4 flex items-start justify-between gap-4">
        <div>
          {editingTitle === null ? (
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-slate-900">{episode.title}</h1>
              <button onClick={() => setEditingTitle(episode.title)} className="text-xs text-brand hover:underline">Rename</button>
            </div>
          ) : (
            <form className="flex items-center gap-2" onSubmit={ev => { ev.preventDefault(); void act(() => updateEpisode(episode.id, { title: editingTitle })).then(() => setEditingTitle(null)); }}>
              <input aria-label="Case title" value={editingTitle} onChange={e => setEditingTitle(e.target.value)} className="rounded-lg border border-slate-200 px-3 py-1.5 text-lg" />
              <button disabled={busy || !editingTitle.trim()} className={`${btn} bg-brand text-white`}>Save</button>
              <button type="button" onClick={() => setEditingTitle(null)} className="text-sm text-slate-500">Cancel</button>
            </form>
          )}
          <Link to={`/patients/${episode.patientId}`} className="mt-1 inline-block text-sm text-brand hover:underline">{episode.patientName}</Link>
        </div>
        <StatusBadge tone={open ? "green" : "gray"}>{open ? "Open" : "Closed"}</StatusBadge>
      </div>

      <div className="mt-6 grid max-w-3xl grid-cols-2 gap-4 rounded-xl border border-slate-200 bg-white p-5 text-sm">
        <div><div className="text-xs uppercase tracking-wide text-slate-500">Doctor</div><div className="mt-0.5 font-medium text-slate-900">{episode.doctorName ?? "No doctor"}</div></div>
        <div><div className="text-xs uppercase tracking-wide text-slate-500">Opened</div><div className="mt-0.5 font-medium text-slate-900">{when(episode.openedAt)}</div></div>
        {episode.closedAt && <div><div className="text-xs uppercase tracking-wide text-slate-500">Closed</div><div className="mt-0.5 font-medium text-slate-900">{when(episode.closedAt)}</div></div>}
        {episode.outcomeNote && <div className="col-span-2"><div className="text-xs uppercase tracking-wide text-slate-500">Outcome</div><p className="mt-0.5 whitespace-pre-wrap text-slate-900">{episode.outcomeNote}</p></div>}
        <div className="col-span-2 flex items-end gap-2">
          <div className="flex-1"><DoctorSelect label="Change doctor" value={doctorChoice} onChange={setDoctorChoice} emptyLabel="Choose a doctor" /></div>
          <button disabled={busy || !doctorChoice || doctorChoice === episode.doctorId}
            onClick={() => void act(() => updateEpisode(episode.id, { doctorId: doctorChoice }))}
            className={`${btn} border border-slate-200 text-slate-700`}>Save doctor</button>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {open ? (
          <>
            <Link to={`/calendar/new?${withCase}`} className={`${btn} bg-brand text-white`}>New appointment</Link>
            <Link to={`/consent/new?${withCase}`} className={`${btn} border border-slate-200 text-slate-700`}>New consent</Link>
            <button onClick={() => setCloseNote("")} className={`${btn} border border-slate-200 text-slate-700`}>Close case</button>
          </>
        ) : (
          <button disabled={busy} onClick={() => void act(() => reopenEpisode(episode.id))} className={`${btn} bg-brand text-white`}>Reopen case</button>
        )}
      </div>

      {closeNote !== null && (
        <form className="mt-4 max-w-3xl rounded-xl border border-slate-200 bg-white p-4"
          onSubmit={ev => { ev.preventDefault(); void act(() => closeEpisode(episode.id, closeNote)).then(() => setCloseNote(null)); }}>
          <label htmlFor="outcome-note" className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Outcome note</label>
          <textarea id="outcome-note" value={closeNote} onChange={e => setCloseNote(e.target.value)} placeholder="How was this resolved?"
            className="mt-1.5 h-24 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" />
          <div className="mt-2 flex gap-2">
            <button disabled={busy || !closeNote.trim()} className={`${btn} bg-brand text-white`}>Close case</button>
            <button type="button" onClick={() => setCloseNote(null)} className="text-sm text-slate-500">Cancel</button>
          </div>
        </form>
      )}

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      <h2 className="mt-8 text-sm font-semibold text-slate-900">Timeline</h2>
      <div className="mt-2 max-w-4xl overflow-hidden rounded-xl border border-slate-200 bg-white">
        {episode.timeline.length === 0 ? (
          <p className="px-5 py-6 text-sm text-slate-500">Nothing in this case yet.</p>
        ) : episode.timeline.map(entry => {
          const link = openLink(entry);
          const movable = entry.kind !== "review";
          return (
            <div key={`${entry.kind}-${entry.id}`} className="border-b border-slate-100 px-5 py-3 text-sm last:border-0">
              <div className="flex items-center gap-4">
                <span className="w-28 shrink-0 text-xs font-semibold uppercase tracking-wide text-slate-500">{KIND_LABEL[entry.kind]}</span>
                <span className="flex-1 text-slate-900">{entry.label}</span>
                <span className="w-24 shrink-0 text-xs capitalize text-slate-500">{entry.status?.replace(/_/g, " ")}</span>
                <span className="w-40 shrink-0 text-right text-xs text-slate-500">{when(entry.at)}</span>
                <span className="w-10 shrink-0">{link && <Link to={link} className="text-xs font-medium text-brand hover:underline">Open</Link>}</span>
                <span className="w-10 shrink-0">{movable && <button onClick={() => setMoving({ entry, target: others[0]?.id ?? NEW_CASE, title: "" })} className="text-xs text-slate-500 hover:text-slate-700">Move</button>}</span>
              </div>
              {moving?.entry === entry && (
                <form className="mt-2 flex items-center gap-2"
                  onSubmit={ev => {
                    ev.preventDefault();
                    const target = moving.target === NEW_CASE ? null : moving.target;
                    void act(() => moveToEpisode({ kind: entry.kind as "contact" | "appointment" | "consent", itemId: entry.id, targetEpisodeId: target, newTitle: moving.title || undefined }))
                      .then(() => setMoving(null));
                  }}>
                  <select aria-label="Move to case" value={moving.target} onChange={e => setMoving({ ...moving, target: e.target.value })} className="rounded-lg border border-slate-200 px-2 py-1.5 text-sm">
                    {others.map(o => <option key={o.id} value={o.id}>{o.title}</option>)}
                    <option value={NEW_CASE}>New case…</option>
                  </select>
                  {moving.target === NEW_CASE && <input aria-label="New case title" value={moving.title} onChange={e => setMoving({ ...moving, title: e.target.value })} placeholder="New case title" className="rounded-lg border border-slate-200 px-2 py-1.5 text-sm" />}
                  <button disabled={busy} className={`${btn} bg-brand py-1.5 text-white`}>Move</button>
                  <button type="button" onClick={() => setMoving(null)} className="text-xs text-slate-500">Cancel</button>
                </form>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
