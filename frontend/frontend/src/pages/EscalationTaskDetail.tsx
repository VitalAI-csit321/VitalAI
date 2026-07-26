import { useEffect, useState } from "react";
import { listUsers } from "../api/auth";
import { addComment, listComments, updateTask } from "../api/tasks";
import type { ManagedUser, Task, TaskComment, TaskItemStatus } from "../api/types";

const STATUS_ACTIONS: { to: TaskItemStatus; label: string }[] = [
  { to: "in_progress", label: "Start review" },
  { to: "escalated", label: "Escalate" },
  { to: "completed", label: "Mark resolved" },
];

export function EscalationTaskDetail({ task: initialTask, onClose, onUpdated }: { task: Task; onClose: () => void; onUpdated?: (task: Task) => void }) {
  const [task, setTask] = useState(initialTask);
  const [comment, setComment] = useState("");
  const [comments, setComments] = useState<TaskComment[]>([]);
  const [postingComment, setPostingComment] = useState(false);
  const [commentError, setCommentError] = useState<string | null>(null);
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [reassignTo, setReassignTo] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    listUsers({ limit: 100 }).then(r => setUsers(r.items)).catch(() => {});
    listComments(task.id).then(setComments).catch(() => {});
  }, [task.id]);

  function authorName(authorId: string): string {
    return users.find(u => u.id === authorId)?.fullName ?? `user-${authorId.slice(0, 8)}`;
  }

  async function submitComment() {
    if (!comment.trim()) return;
    setPostingComment(true);
    setCommentError(null);
    try {
      const created = await addComment(task.id, comment.trim());
      setComments(prev => [...prev, created]);
      setComment("");
    } catch {
      setCommentError("Could not post the comment. Try again.");
    } finally {
      setPostingComment(false);
    }
  }

  async function applyUpdate(payload: { status?: TaskItemStatus; assigned_to?: string }) {
    setBusy(JSON.stringify(payload));
    setActionError(null);
    try {
      const updated = await updateTask(task.id, payload);
      setTask(updated);
      onUpdated?.(updated);
    } catch {
      setActionError("Could not update the task. Try again.");
    } finally {
      setBusy(null);
    }
  }

  const ref = `T-${task.id.slice(0, 6)}`;
  const isEscalated = task.status === "escalated";
  const isHighPriority = task.priority === "urgent" || task.priority === "high";
  const fmt = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

  let handover: Record<string, unknown> | null = null;
  if (task.handoverContext) {
    try { handover = JSON.parse(task.handoverContext); } catch { handover = null; }
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} />
      <div className="fixed inset-0 z-40 flex items-center justify-center p-6 pointer-events-none">
        <div className="pointer-events-auto w-full max-w-5xl rounded-2xl bg-white shadow-2xl overflow-hidden max-h-[90vh] overflow-y-auto">
          <div className="p-6">
            <div className="flex items-start justify-between">
              <div>
                <h1 className="text-2xl font-bold text-slate-900">{task.subject ?? `Task ${ref}`}</h1>
                <p className="mt-1 text-sm text-slate-500">
                  {task.fromName ?? (task.targetQueue ? task.targetQueue.replace(/_/g, " ") : "No queue assigned")}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {isEscalated && <span className="rounded bg-red-100 px-2.5 py-1 text-xs font-bold uppercase text-red-600">Escalated</span>}
                {isHighPriority && <span className="rounded bg-orange-100 px-2.5 py-1 text-xs font-bold text-orange-600">High priority</span>}
                <button onClick={onClose} className="ml-4 text-slate-400 hover:text-slate-600 text-xl">×</button>
              </div>
            </div>

            <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1.5fr_1fr]">
              <div className="space-y-6">
                <div className="rounded-xl border border-slate-200 p-5">
                  <h2 className="text-base font-semibold text-slate-900 mb-4">Task information</h2>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    {[["Task ID", ref], ["Source", task.source], ["Priority", task.priority.charAt(0).toUpperCase()+task.priority.slice(1)], ["Status", task.status.replace("_", " ").replace(/\b\w/g, c => c.toUpperCase())], ["Created", fmt(task.createdAt)], ["Assigned to", task.assignedTo ? `user-${task.assignedTo.slice(0,8)}` : "Unassigned"]].map(([l, v]) => (
                      <div key={l}><div className="text-xs text-slate-500 uppercase tracking-wide">{l}</div><div className="font-medium text-slate-900 mt-0.5">{v}</div></div>
                    ))}
                  </div>
                  <div className="mt-4">
                    <div className="text-xs text-slate-500 uppercase tracking-wide mb-1">Handover context</div>
                    {handover ? (
                      <div className="space-y-1.5 text-sm text-slate-700">
                        {handover.transcript ? <p><span className="text-slate-500">Transcript: </span>{String(handover.transcript)}</p> : null}
                        {handover.routing_rationale ? <p><span className="text-slate-500">Routing rationale: </span>{String(handover.routing_rationale)}</p> : null}
                        {handover.escalation_reason ? <p><span className="text-slate-500">Reason: </span>{String(handover.escalation_reason)}</p> : null}
                      </div>
                    ) : (
                      <p className="text-sm text-slate-500">No additional context attached to this task.</p>
                    )}
                  </div>

                  <div className="mt-5">
                    <h3 className="text-sm font-semibold text-slate-900 mb-3">Timeline</h3>
                    <div className="space-y-3">
                      <div className="flex items-start gap-3"><span className="mt-1.5 h-2.5 w-2.5 rounded-full shrink-0 bg-brand" /><div><div className="text-sm font-medium text-slate-900">Created</div><div className="text-xs text-slate-500">{fmt(task.createdAt)}</div></div></div>
                      {task.updatedAt !== task.createdAt && <div className="flex items-start gap-3"><span className="mt-1.5 h-2.5 w-2.5 rounded-full shrink-0 bg-slate-300" /><div><div className="text-sm font-medium text-slate-900">Last updated</div><div className="text-xs text-slate-500">{fmt(task.updatedAt)}</div></div></div>}
                    </div>
                  </div>
                </div>

                <div className="rounded-xl border border-slate-200 p-5">
                  <h2 className="text-base font-semibold text-slate-900 mb-4">Comments</h2>
                  {comments.length === 0 ? (
                    <p className="text-sm text-slate-400 mb-4">No comments yet.</p>
                  ) : (
                    <div className="space-y-3 mb-4">
                      {comments.map(c => (
                        <div key={c.id} className="rounded-lg bg-slate-50 p-3">
                          <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
                            <span className="font-semibold text-slate-700">{authorName(c.authorId)}</span>
                            <span>{fmt(c.createdAt)}</span>
                          </div>
                          <p className="text-sm text-slate-800 whitespace-pre-wrap">{c.body}</p>
                        </div>
                      ))}
                    </div>
                  )}
                  <textarea value={comment} onChange={e => setComment(e.target.value)}
                    placeholder="Add a comment..."
                    className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-brand resize-none h-24" />
                  <button onClick={submitComment} disabled={postingComment || !comment.trim()}
                    className="mt-3 flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50">
                    ➤ {postingComment ? "Posting…" : "Post comment"}
                  </button>
                  {commentError && <p className="mt-2 text-sm text-red-600">{commentError}</p>}
                </div>
              </div>

              <div className="space-y-4">
                <div className="rounded-xl border border-slate-200 p-5">
                  <h2 className="text-base font-semibold text-slate-900 mb-4">Status</h2>
                  <div className="space-y-2">
                    {STATUS_ACTIONS.filter(a => a.to !== task.status).map(a => (
                      <button key={a.to} onClick={() => applyUpdate({ status: a.to })} disabled={busy !== null}
                        className="w-full rounded-lg border border-slate-200 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50">
                        {busy === JSON.stringify({ status: a.to }) ? "Updating…" : a.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="rounded-xl border border-slate-200 p-5">
                  <h2 className="text-base font-semibold text-slate-900 mb-4">Assignment</h2>
                  <div className="text-sm text-slate-700 mb-4">{task.assignedTo ? (users.find(u => u.id === task.assignedTo)?.fullName ?? `user-${task.assignedTo.slice(0,8)}`) : "Unassigned"}</div>
                  <select value={reassignTo} onChange={e => setReassignTo(e.target.value)}
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand mb-3">
                    <option value="">Select a user...</option>
                    {users.map(u => <option key={u.id} value={u.id}>{u.fullName}</option>)}
                  </select>
                  <button onClick={() => reassignTo && applyUpdate({ assigned_to: reassignTo })} disabled={!reassignTo || busy !== null}
                    className="w-full rounded-lg bg-brand py-2.5 text-sm font-semibold text-white hover:bg-brand-hover disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400">
                    {busy === JSON.stringify({ assigned_to: reassignTo }) ? "Updating…" : "Update assignment"}
                  </button>
                </div>
                {actionError && <p className="text-sm text-red-600">{actionError}</p>}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
