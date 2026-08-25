import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createReviewTask } from "../api/reviewTasks";
import { listUsers } from "../api/auth";
import type { ManagedUser } from "../api/types";

const TASK_TYPES = [
  { value: "triage_review", label: "Triage review" },
  { value: "consent_review", label: "Consent review" },
  { value: "escalation_review", label: "Escalation review" },
  { value: "routing_review", label: "Routing review" },
];

export function AddCasePage() {
  const navigate = useNavigate();
  const [contactReason, setContactReason] = useState("");
  const [taskType, setTaskType] = useState("triage_review");
  const [priority, setPriority] = useState<"low" | "medium" | "high">("medium");
  const [assignedTo, setAssignedTo] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listUsers({ limit: 100 }).then(r => setUsers(r.items)).catch(() => {});
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!contactReason.trim()) { setError("Reason is required."); return; }
    setSubmitting(true);
    setError(null);
    try {
      await createReviewTask({
        task_type: taskType,
        contact_reason: contactReason,
        priority,
        assigned_to: assignedTo || null,
        reviewed,
      });
      navigate("/review-queue");
    } catch {
      setError("Could not create this case.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="p-6 max-w-lg">
      <button onClick={() => navigate(-1)} className="text-sm text-slate-500 hover:text-slate-700">← Back</button>
      <h1 className="mt-4 text-2xl font-bold text-slate-900">Add case</h1>
      <p className="mt-1 text-sm text-slate-500">Manually log an independent case into the review queue.</p>

      <form onSubmit={handleSubmit} className="mt-6 space-y-4 rounded-xl border border-slate-200 bg-white p-5">
        <div>
          <label className="block text-sm font-medium text-slate-700">Reason</label>
          <input
            value={contactReason}
            onChange={e => setContactReason(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="Why this case is being logged"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700">Type</label>
          <select value={taskType} onChange={e => setTaskType(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
            {TASK_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700">Priority</label>
          <select value={priority} onChange={e => setPriority(e.target.value as "low"|"medium"|"high")} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700">Owner</label>
          <select value={assignedTo} onChange={e => setAssignedTo(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
            <option value="">Unassigned</option>
            {users.map(u => <option key={u.id} value={u.id}>{u.fullName} ({u.email})</option>)}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <input id="reviewed" type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} className="h-4 w-4 rounded border-slate-300" />
          <label htmlFor="reviewed" className="text-sm text-slate-700">Already reviewed</label>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button type="submit" disabled={submitting} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50">
          {submitting ? "Creating..." : "Create case"}
        </button>
      </form>
    </div>
  );
}
