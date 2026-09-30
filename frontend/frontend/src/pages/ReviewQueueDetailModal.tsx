import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { formatDateTime } from "../lib/format";
import { Link, useNavigate } from "react-router-dom";
import { approveDraft, getInboxMessage, rejectDraft, sendManualReply } from "../api/misc";
import { listDoctors } from "../api/doctors";
import {
  KIND_LABEL, answerCaseClose, chooseCase, claimReviewTask, completeReviewTask, dismissReviewTask,
  escalateReviewTask, isOpen, linkReviewPatient, reassignReviewTask, rerouteReviewTask, type RawReviewTask,
} from "../api/reviewTasks";
import { TASK_CATEGORIES } from "../api/tasks";
import type { Doctor, Message } from "../api/types";
import { describeApiError } from "../lib/apiClient";
import { useAuth } from "../lib/auth";

const btn = "w-full rounded-lg py-2.5 text-sm font-semibold disabled:opacity-50";

export function ReviewQueueDetailModal({ item, onClose, onDone }: { item: RawReviewTask; onClose: () => void; onDone: () => void }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [message, setMessage] = useState<Message | null>(null);
  const [draft, setDraft] = useState("");
  const [reply, setReply] = useState("");
  const [note, setNote] = useState("");
  const [category, setCategory] = useState(item.details?.category ?? "");
  const [patientId, setPatientId] = useState("");
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [doctorId, setDoctorId] = useState("");
  // Cases (M4): the chosen case ("" = a new one) and the outcome note to close one.
  const [caseChoice, setCaseChoice] = useState(item.details?.suggested_episode_id ?? "");
  const [outcome, setOutcome] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const kind = item.task_type;
  const open = isOpen(item);
  const canReassign = kind === "draft_approval" && (user?.role === "operator" || user?.role === "admin");
  // Re-route acts on the message, so a manual routing case (no message) is closed with Done.
  const rerouting = (kind === "routing_review" || kind === "intent_review") && !!item.inbox_task_id;
  // Write reply (D14): server-decided, and never alongside a draft awaiting approval.
  const writing = message?.canWriteReply ?? false;
  const caseKind = kind === "case_choice" || kind === "case_close";

  // A closed item just shows its stored reason and status below -- no
  // source message fetch, and so no fetch error either.
  useEffect(() => {
    if (!item.inbox_task_id || !open) return;
    getInboxMessage(item.inbox_task_id)
      .then(m => { setMessage(m); setDraft(m.draftText ?? ""); })
      .catch(() => setError("Could not load the message."));
  }, [item.inbox_task_id, open]);

  useEffect(() => {
    if (canReassign) listDoctors().then(setDoctors).catch(() => {});
  }, [canReassign]);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try {
      if (item.status === "pending") await claimReviewTask(item.id);
      await fn();
      onDone();
    } catch (e) {
      setError(describeApiError(e, "Could not record the decision."));
    } finally {
      setBusy(false);
    }
  }

  const noteMissing = note.trim().length === 0;
  const approve = () => run(() => approveDraft(item.approval_id!, draft.trim() !== (message?.draftText ?? "").trim() && message?.emailId
    ? { draft, emailId: message.emailId, taskId: item.inbox_task_id! } : undefined));

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} />
      <div className="fixed inset-0 z-40 flex items-center justify-center p-6 pointer-events-none">
        <div className="pointer-events-auto w-full max-w-5xl max-h-[90vh] overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl">
          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-2xl font-bold text-slate-900">{KIND_LABEL[kind] ?? kind}</h1>
              {item.case_id
                ? <p className="text-sm text-slate-500">Contact C-{item.case_id.slice(0, 8)}</p>
                : item.episode_id && <Link to={`/cases/${item.episode_id}`} className="text-sm text-brand hover:underline">Case: {item.case_title}</Link>}
            </div>
            <button onClick={onClose} aria-label="Close" className="text-xl text-slate-400 hover:text-slate-600">×</button>
          </div>
          <div className="mt-6 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
            <div className="space-y-5">
              <div className="grid grid-cols-2 gap-4 rounded-xl border border-slate-200 p-5 text-sm">
                {[["Patient", item.patient_name ?? "Unidentified"], ["Channel", item.channel ?? "-"],
                  ["Owner", item.owner_label ?? "-"], ["Priority", item.priority],
                  ["Submitted", formatDateTime(item.created_at)],
                  ["Due", item.due_at ? formatDateTime(item.due_at) : "No due date"]].map(([l, v]) => (
                  <div key={l}><div className="text-xs text-slate-500">{l}</div><div className="mt-0.5 font-medium capitalize text-slate-900">{v}</div></div>
                ))}
                <div className="col-span-2"><div className="text-xs text-slate-500">Reason</div><p className="mt-0.5 whitespace-pre-wrap text-slate-900">{item.notes ?? "-"}</p></div>
                {item.details?.escalation && (
                  <div className="col-span-2 rounded-lg bg-red-50 p-3 text-red-900">Escalated by {item.details.escalation.by}: {item.details.escalation.note}</div>
                )}
              </div>
              {message && (
                <div className="rounded-xl border border-slate-200 p-5 text-sm">
                  <div className="text-xs text-slate-500">From {message.fromName}</div>
                  <h2 className="mt-1 font-semibold text-slate-900">{message.subject}</h2>
                  <p className="mt-3 whitespace-pre-line text-slate-700">{message.body}</p>
                  {kind === "draft_approval" && message.draftText && !writing && (
                    message.draftSent
                      ? <p className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-emerald-700"><Check className="h-4 w-4" aria-hidden />Already sent</p>
                      : <textarea aria-label="Draft reply" value={draft} onChange={e => setDraft(e.target.value)} disabled={busy || !open}
                          rows={6} className="mt-4 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" />
                  )}
                  {writing && (
                    <>
                      <label htmlFor="rq-reply" className="mt-4 block text-xs font-medium text-slate-600">Write reply</label>
                      <textarea id="rq-reply" value={reply} onChange={e => setReply(e.target.value)} disabled={busy} maxLength={10000}
                        rows={6} className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" />
                    </>
                  )}
                </div>
              )}
              {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
            </div>
            {open && (
              <div className="space-y-2 rounded-xl border border-slate-200 p-5">
                <h2 className="mb-2 font-semibold text-slate-900">Decision</h2>
                {kind === "draft_approval" && message?.canApprove && !message.draftSent && (
                  <button onClick={approve} disabled={busy || !draft.trim()} className={`${btn} bg-brand text-white`}>Approve & send</button>
                )}
                {writing && (
                  <button onClick={() => run(() => sendManualReply(item.inbox_task_id!, reply))} disabled={busy || !reply.trim()} className={`${btn} bg-brand text-white`}>Send</button>
                )}
                {rerouting && (
                  <>
                    <label className="block text-xs font-medium text-slate-600" htmlFor="rq-category">Category</label>
                    <select id="rq-category" value={category} onChange={e => setCategory(e.target.value)} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm">
                      {TASK_CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                    </select>
                    <button onClick={() => run(() => rerouteReviewTask(item.id, category))} disabled={busy || !category} className={`${btn} bg-brand text-white`}>Re-route</button>
                    <button onClick={() => run(() => completeReviewTask(item.id, "Category confirmed"))} disabled={busy} className={`${btn} border border-slate-200 text-slate-700`}>Confirm category</button>
                  </>
                )}
                {kind === "identity_review" && (
                  <>
                    {(item.candidates ?? []).map(c => (
                      <label key={c.id} className="flex items-center gap-2 text-sm"><input type="radio" name="rq-patient" value={c.id} checked={patientId === c.id} onChange={() => setPatientId(c.id)} />{c.name} ({c.dob})</label>
                    ))}
                    <button onClick={() => run(() => linkReviewPatient(item.id, patientId))} disabled={busy || !patientId} className={`${btn} bg-brand text-white`}>Link patient</button>
                    <button onClick={() => run(() => linkReviewPatient(item.id, null))} disabled={busy} className={`${btn} border border-slate-200 text-slate-700`}>None of these</button>
                  </>
                )}
                {kind === "case_choice" && (
                  <>
                    {(item.case_candidates ?? []).map(c => (
                      <label key={c.id} className="flex items-center gap-2 text-sm">
                        <input type="radio" name="rq-case" value={c.id} checked={caseChoice === c.id} onChange={() => setCaseChoice(c.id)} />
                        {c.title}{c.id === item.details?.suggested_episode_id && <span className="text-xs text-brand">(suggested)</span>}
                      </label>
                    ))}
                    <label className="flex items-center gap-2 text-sm">
                      <input type="radio" name="rq-case" value="" checked={caseChoice === ""} onChange={() => setCaseChoice("")} />New case
                    </label>
                    <button onClick={() => run(() => chooseCase(item.id, caseChoice || null))} disabled={busy} className={`${btn} bg-brand text-white`}>Put it in this case</button>
                  </>
                )}
                {kind === "case_close" && (
                  <>
                    <label htmlFor="rq-outcome" className="block text-xs font-medium text-slate-600">Outcome note (to close)</label>
                    <textarea id="rq-outcome" value={outcome} onChange={e => setOutcome(e.target.value)} rows={3} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" />
                    <button onClick={() => run(() => answerCaseClose(item.id, true, outcome.trim()))} disabled={busy || !outcome.trim()} className={`${btn} bg-brand text-white`}>Close case</button>
                    <button onClick={() => run(() => answerCaseClose(item.id, false, null))} disabled={busy} className={`${btn} border border-slate-200 text-slate-700`}>Keep open</button>
                    {item.episode_id && <button onClick={() => navigate(`/cases/${item.episode_id}`)} className={`${btn} border border-slate-200 text-slate-700`}>Open case</button>}
                  </>
                )}
                {kind !== "draft_approval" && !rerouting && kind !== "identity_review" && !caseKind && (
                  <button onClick={() => run(() => completeReviewTask(item.id, note.trim() || null))} disabled={busy} className={`${btn} bg-brand text-white`}>Done</button>
                )}
                {item.inbox_task_id && (
                  <button onClick={() => navigate(`/inbox?task=${item.inbox_task_id}`)} className={`${btn} border border-slate-200 text-slate-700`}>Open conversation</button>
                )}
                {canReassign && (
                  <div className="flex gap-2">
                    <select aria-label="Doctor" value={doctorId} onChange={e => setDoctorId(e.target.value)} className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm">
                      <option value="">Choose a doctor…</option>
                      {doctors.map(d => <option key={d.id} value={d.id}>{d.fullName}</option>)}
                    </select>
                    <button onClick={() => run(() => reassignReviewTask(item.id, doctorId))} disabled={busy || !doctorId} className="rounded-lg border border-slate-200 px-3 text-sm font-semibold text-slate-700 disabled:opacity-50">Reassign</button>
                  </div>
                )}
                <label htmlFor="rq-note" className="mt-3 block text-xs font-medium text-slate-600">Note (required to reject, dismiss or escalate)</label>
                <textarea id="rq-note" value={note} onChange={e => setNote(e.target.value)} rows={3} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" />
                {kind === "draft_approval" ? (
                  !writing && <button onClick={() => run(() => rejectDraft(item.approval_id!, note.trim()))} disabled={busy || noteMissing} className={`${btn} bg-red-500 text-white`}>Reject</button>
                ) : (
                  <button onClick={() => run(() => dismissReviewTask(item.id, note.trim()))} disabled={busy || noteMissing} className={`${btn} bg-red-500 text-white`}>Dismiss</button>
                )}
                {user?.role !== "admin" && (
                  <button onClick={() => run(() => escalateReviewTask(item.id, note.trim()))} disabled={busy || noteMissing} className={`${btn} bg-amber-500 text-white`}>Escalate</button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
