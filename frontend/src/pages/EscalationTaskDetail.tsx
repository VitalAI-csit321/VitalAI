import { useState } from "react";
import type { Task } from "../api/types";
import { Avatar } from "../components/ui";
import { updateTask } from "../api/tasks";

interface TaskMeta {
  ref: string; title: string; subtitle: string; initials: string; color: string; age: string; dot: boolean;
}

export function EscalationTaskDetail({ task, meta, onClose }: { task: Task; meta: TaskMeta; onClose: () => void }) {
  const [comment, setComment] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const isEscalated = task.status === "escalated";
  const isHighPriority = task.priority === "urgent" || task.priority === "high";

  const statusHistory = [
    { label: "Escalated", time: "22 May 2026, 11:16" },
    { label: "Under review", time: "22 May 2026, 11:15" },
    { label: "Created", time: "22 May 2026, 11:15" },
  ];

  const timeline = [
    { dot: "bg-brand", label: "Task created", time: "22 May 2026, 11:15" },
    { dot: "bg-red-500", label: "Override attempt blocked", time: "22 May 2026, 11:16" },
    { dot: "bg-amber-400", label: "Auto-escalated", time: "22 May 2026, 11:16" },
    { dot: "bg-slate-300", label: "Under review", time: "Current status" },
  ];

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} />
      <div className="fixed inset-0 z-40 flex items-center justify-center p-6 pointer-events-none">
        <div className="pointer-events-auto w-full max-w-5xl rounded-2xl bg-white shadow-2xl overflow-hidden max-h-[90vh] overflow-y-auto">
          <div className="p-6">
            <div className="flex items-start justify-between">
              <div>
                <h1 className="text-2xl font-bold text-slate-900">Task {meta.ref}</h1>
                <p className="mt-1 text-sm text-slate-500">{meta.subtitle}</p>
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
                    {[["Task ID", meta.ref], ["Type", "HITL override"], ["Priority", task.priority.charAt(0).toUpperCase()+task.priority.slice(1)], ["Status", task.status.replace("_", " ").replace(/\b\w/g, c => c.toUpperCase())], ["Created", "22 May 2026, 11:15"], ["Assigned to", "Dr S. Kapoor"]].map(([l, v]) => (
                      <div key={l}><div className="text-xs text-slate-500 uppercase tracking-wide">{l}</div><div className="font-medium text-slate-900 mt-0.5">{v}</div></div>
                    ))}
                  </div>
                  <div className="mt-4">
                    <div className="text-xs text-slate-500 uppercase tracking-wide mb-1">Description</div>
                    <p className="text-sm text-slate-700">User attempted to override an automated HITL decision without proper authorization. The system blocked this action and automatically escalated the incident for review. This requires immediate attention from a senior administrator.</p>
                  </div>

                  <div className="mt-5">
                    <h3 className="text-sm font-semibold text-slate-900 mb-3">Timeline</h3>
                    <div className="space-y-3">
                      {timeline.map(e => (
                        <div key={e.label} className="flex items-start gap-3">
                          <span className={`mt-1.5 h-2.5 w-2.5 rounded-full shrink-0 ${e.dot}`} />
                          <div><div className="text-sm font-medium text-slate-900">{e.label}</div><div className="text-xs text-slate-500">{e.time}</div></div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="rounded-xl border border-slate-200 p-5">
                  <textarea value={comment} onChange={e => setComment(e.target.value)}
                    placeholder="Add a comment..."
                    className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-brand resize-none h-24" />
                  <button onClick={() => { if (comment) setSubmitted(true); }}
                    className="mt-3 flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover">
                    ➤ Post comment
                  </button>
                  {submitted && <p className="mt-2 text-sm text-brand">Comment posted.</p>}
                </div>
              </div>

              <div className="space-y-4">
                <div className="rounded-xl border border-slate-200 p-5">
                  <h2 className="text-base font-semibold text-slate-900 mb-4">Assignment</h2>
                  <div className="flex items-center gap-3 mb-4">
                    <Avatar initials={meta.initials} color={meta.color} size={36} />
                    <div><div className="text-sm font-semibold text-slate-900">Dr Sanjay Kapoor</div><div className="text-xs text-slate-500">Clinical Lead</div></div>
                  </div>
                  <input placeholder="Reassign to..." className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand mb-3" />
                  <button className="w-full rounded-lg bg-brand py-2.5 text-sm font-semibold text-white hover:bg-brand-hover">Update assignment</button>
                </div>

                <div className="rounded-xl border border-slate-200 p-5">
                  <h2 className="text-base font-semibold text-slate-900 mb-4">Status history</h2>
                  <div className="space-y-3">
                    {statusHistory.map(s => (
                      <div key={s.label}><div className="text-sm font-medium text-slate-900">{s.label}</div><div className="text-xs text-slate-500">{s.time}</div></div>
                    ))}
                  </div>
                </div>

                {isEscalated && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
                    <div className="flex items-start gap-2">
                      <span className="text-amber-500 text-lg">⚠</span>
                      <div>
                        <p className="text-sm font-semibold text-amber-800">RBAC violation detected</p>
                        <p className="mt-1 text-sm text-amber-700">User attempted action without sufficient permissions. Access denied and logged.</p>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
