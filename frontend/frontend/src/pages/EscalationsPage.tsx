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

const AVATAR_COLORS = ["#0d9488", "#eab308", "#7c3aed", "#db2777", "#0891b2", "#f97316"];

function relativeAge(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const hours = Math.floor(ms / (1000 * 60 * 60));
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function formatCategory(category: string): string {
  return category
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function TaskCard({ task, onClick }: { task: Task; onClick: () => void }) {
  const ref = `T-${task.id.slice(0, 6)}`;
  const fallbackTitle = `${task.source === "call" ? "Call" : "Email"} escalation`;
  const title = task.subject ?? fallbackTitle;
  const subtitle = task.fromName
    ?? (task.targetQueue ? task.targetQueue.replace(/_/g, " ") : "No sender on record");
  const initials = task.fromName
    ? task.fromName.slice(0, 2).toUpperCase()
    : task.assignedTo
      ? task.assignedTo.slice(0, 2).toUpperCase()
      : "?";
  const color = AVATAR_COLORS[task.id.charCodeAt(0) % AVATAR_COLORS.length];
  const highPriority = task.priority === "urgent" || task.priority === "high";

  return (
    <button onClick={onClick} className="w-full rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between mb-2">
        <span className="text-xs font-semibold text-slate-500">{ref}</span>
        <span className={`h-2 w-2 rounded-full mt-1 ${highPriority ? "bg-slate-900" : "bg-slate-300"}`} />
      </div>
      <p className="truncate text-sm font-semibold text-slate-900">{title}</p>
      <p className="mt-0.5 truncate text-xs text-slate-500">{subtitle}</p>
      {task.category && (
        <span className="mt-1.5 inline-block rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
          {formatCategory(task.category)}
        </span>
      )}
      <div className="mt-3 flex items-center justify-between">
        <Avatar initials={initials} color={color} size={28} />
        <span className="text-xs text-slate-400">{relativeAge(task.createdAt)}</span>
      </div>
    </button>
  );
}

export function EscalationsPage() {
  const [board, setBoard] = useState<TaskBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Task | null>(null);

  useEffect(() => {
    getTaskBoard()
      .then(setBoard)
      .catch(() => setError("Could not load escalations."))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-8"><Spinner /></div>;
  if (error || !board) return <div className="p-6"><p className="text-sm text-red-600">{error ?? "No data."}</p></div>;

  const totalActive = board.counts.pending + board.counts.in_progress + board.counts.escalated;

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Escalation routing</h1>
          <p className="mt-1 text-sm text-slate-500">{totalActive} active • {board.counts.escalated} escalated</p>
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
              {(board.columns[col.key] ?? []).length === 0 ? (
                <p className="text-xs text-slate-400">Nothing here.</p>
              ) : (board.columns[col.key] ?? []).map(task => (
                <TaskCard key={task.id} task={task} onClick={() => setSelected(task)} />
              ))}
            </div>
          </div>
        ))}
      </div>

      {selected && (
        <EscalationTaskDetail
          task={selected}
          onClose={() => setSelected(null)}
          onUpdated={updated => {
            setSelected(updated);
            getTaskBoard().then(setBoard).catch(() => {});
          }}
        />
      )}
    </div>
  );
}
