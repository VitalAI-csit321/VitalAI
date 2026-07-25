import { useEffect, useState } from "react";
import { getTaskBoard } from "../api/tasks";
import type { Task, TaskBoard } from "../api/types";
import { Avatar, Spinner } from "../components/ui";
import { EscalationTaskDetail } from "./EscalationTaskDetail";

const COL_CONFIG = [
  { key: "pending", label: "Submitted", dot: "bg-slate-400" },
  { key: "in_progress", label: "Under review", dot: "bg-amber-400" },
  { key: "escalated", label: "Escalated", dot: "bg-red-500" },
  { key: "completed", label: "Resolved", dot: "bg-brand" },
];

// Rich placeholder tasks matching the approved design
const PLACEHOLDER_BOARD: TaskBoard = {
  columns: {
    pending: [
      { id: "t2156", caseId: "c1", assignedTo: null, source: "call", priority: "medium", status: "pending", createdAt: "2026-05-22T12:00:00Z", updatedAt: "2026-05-22T12:00:00Z" },
      { id: "t2155", caseId: "c2", assignedTo: null, source: "email", priority: "low", status: "pending", createdAt: "2026-05-22T11:00:00Z", updatedAt: "2026-05-22T11:00:00Z" },
      { id: "t2154", caseId: "c3", assignedTo: null, source: "call", priority: "high", status: "pending", createdAt: "2026-05-22T09:00:00Z", updatedAt: "2026-05-22T09:00:00Z" },
    ],
    in_progress: [
      { id: "t2145", caseId: "c4", assignedTo: "sk", source: "call", priority: "urgent", status: "in_progress", createdAt: "2026-05-21T14:00:00Z", updatedAt: "2026-05-21T14:00:00Z" },
      { id: "t2142", caseId: "c5", assignedTo: "ma", source: "email", priority: "medium", status: "in_progress", createdAt: "2026-05-21T13:00:00Z", updatedAt: "2026-05-21T13:00:00Z" },
      { id: "t2140", caseId: "c6", assignedTo: "ch", source: "call", priority: "low", status: "in_progress", createdAt: "2026-05-20T10:00:00Z", updatedAt: "2026-05-20T10:00:00Z" },
    ],
    escalated: [
      { id: "t2101", caseId: "c7", assignedTo: "sk", source: "call", priority: "urgent", status: "escalated", createdAt: "2026-05-22T11:15:00Z", updatedAt: "2026-05-22T11:16:00Z" },
      { id: "t2098", caseId: "c8", assignedTo: "sk", source: "email", priority: "high", status: "escalated", createdAt: "2026-05-21T12:00:00Z", updatedAt: "2026-05-21T12:00:00Z" },
      { id: "t2095", caseId: "c9", assignedTo: "at", source: "call", priority: "medium", status: "escalated", createdAt: "2026-05-20T09:00:00Z", updatedAt: "2026-05-20T09:00:00Z" },
    ],
    completed: [
      { id: "t2089", caseId: "c10", assignedTo: "lk", source: "email", priority: "low", status: "completed", createdAt: "2026-05-19T14:00:00Z", updatedAt: "2026-05-19T16:00:00Z" },
      { id: "t2085", caseId: "c11", assignedTo: "jt", source: "call", priority: "medium", status: "completed", createdAt: "2026-05-18T10:00:00Z", updatedAt: "2026-05-18T12:00:00Z" },
      { id: "t2082", caseId: "c12", assignedTo: "mc", source: "email", priority: "high", status: "completed", createdAt: "2026-05-17T09:00:00Z", updatedAt: "2026-05-17T11:00:00Z" },
    ],
  },
  counts: { pending: 12, in_progress: 8, escalated: 3, completed: 24 },
};

const TASK_META: Record<string, { ref: string; title: string; subtitle: string; initials: string; color: string; age: string; dot: boolean }> = {
  t2156: { ref: "T-2156", title: "Consent review delay", subtitle: "Patient waiting for approval", initials: "LK", color: "#eab308", age: "2 hours ago", dot: false },
  t2155: { ref: "T-2155", title: "Record query", subtitle: "Missing documentation", initials: "JT", color: "#db2777", age: "3 hours ago", dot: false },
  t2154: { ref: "T-2154", title: "Policy violation flag", subtitle: "Automated system alert", initials: "MC", color: "#0d9488", age: "5 hours ago", dot: true },
  t2145: { ref: "T-2145", title: "HITL review needed", subtitle: "Complex case assessment", initials: "SK", color: "#0d9488", age: "1 day ago", dot: true },
  t2142: { ref: "T-2142", title: "Data quality check", subtitle: "Inconsistent records", initials: "MA", color: "#7c3aed", age: "1 day ago", dot: false },
  t2140: { ref: "T-2140", title: "Workflow timeout", subtitle: "Process took too long", initials: "CH", color: "#0891b2", age: "2 days ago", dot: false },
  t2101: { ref: "T-2101", title: "HITL override attempted", subtitle: "Unauthorized action blocked", initials: "MB", color: "#f97316", age: "3 hours ago", dot: true },
  t2098: { ref: "T-2098", title: "Critical consent issue", subtitle: "Legal team review required", initials: "SK", color: "#0d9488", age: "1 day ago", dot: true },
  t2095: { ref: "T-2095", title: "Audit discrepancy", subtitle: "Integrity check failed", initials: "AT", color: "#64748b", age: "2 days ago", dot: false },
  t2089: { ref: "T-2089", title: "Consent form approved", subtitle: "Manual review completed", initials: "LK", color: "#eab308", age: "3 days ago", dot: false },
  t2085: { ref: "T-2085", title: "Record uploaded", subtitle: "Documentation complete", initials: "JT", color: "#db2777", age: "4 days ago", dot: false },
  t2082: { ref: "T-2082", title: "Policy update applied", subtitle: "System reconfigured", initials: "MC", color: "#0d9488", age: "5 days ago", dot: true },
};

function TaskCard({ task, onClick }: { task: Task; onClick: () => void }) {
  const m = TASK_META[task.id] ?? { ref: task.id.slice(0,6), title: `Task ${task.id.slice(0,6)}`, subtitle: task.source, initials: "?", color: "#64748b", age: "recently", dot: false };
  return (
    <button onClick={onClick} className="w-full rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between mb-2">
        <span className="text-xs font-semibold text-slate-500">{m.ref}</span>
        <span className={`h-2 w-2 rounded-full mt-1 ${m.dot ? "bg-slate-900" : "bg-slate-300"}`} />
      </div>
      <p className="text-sm font-semibold text-slate-900">{m.title}</p>
      <p className="text-xs text-slate-500 mt-0.5 mb-3">{m.subtitle}</p>
      <div className="flex items-center justify-between">
        <Avatar initials={m.initials} color={m.color} size={28} />
        <span className="text-xs text-slate-400">{m.age}</span>
      </div>
    </button>
  );
}

export function EscalationsPage() {
  const [board, setBoard] = useState<TaskBoard>(PLACEHOLDER_BOARD);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<{ task: Task; meta: typeof TASK_META[string] } | null>(null);

  useEffect(() => {
    getTaskBoard()
      .then(b => { if (Object.values(b.columns).some(col => col.length > 0)) setBoard(b); })
      .catch(() => {}) // Fall back to placeholder if API returns empty
      .finally(() => setLoading(false));
  }, []);

  const totalActive = (board.counts.pending) + (board.counts.in_progress) + (board.counts.escalated);

  if (loading) return <div className="p-8"><Spinner /></div>;

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Escalation routing</h1>
          <p className="mt-1 text-sm text-slate-500">{totalActive} active • {board.counts.escalated} escalated</p>
        </div>
        <div className="flex gap-3">
          <button className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
            ▼ Filter
          </button>
          <button className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover">New task</button>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-4 gap-4">
        {COL_CONFIG.map(col => (
          <div key={col.key}>
            <div className="flex items-center gap-2 mb-3">
              <span className={`h-2.5 w-2.5 rounded-full ${col.dot}`} />
              <span className="text-sm font-semibold text-slate-800">{col.label}</span>
              <span className="ml-auto text-sm text-slate-500">{board.counts[col.key as keyof typeof board.counts]}</span>
            </div>
            <div className="space-y-3">
              {(board.columns[col.key] ?? []).map(task => (
                <TaskCard key={task.id} task={task} onClick={() => setSelected({ task, meta: TASK_META[task.id] ?? { ref: task.id, title: "Task", subtitle: "", initials: "?", color: "#64748b", age: "recently", dot: false } })} />
              ))}
            </div>
          </div>
        ))}
      </div>

      {selected && <EscalationTaskDetail task={selected.task} meta={selected.meta} onClose={() => setSelected(null)} />}
    </div>
  );
}
