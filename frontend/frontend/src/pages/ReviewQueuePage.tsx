import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Download } from "lucide-react";
import { StatusBadge, Spinner } from "../components/ui";
import { ReviewQueueDetailModal } from "./ReviewQueueDetailModal";
import { KIND_LABEL, isOpen, listReviewTasks, type RawReviewTask } from "../api/reviewTasks";
import { useAuth } from "../lib/auth";

type Tab = "all" | "mine" | "high" | "sla";

const PRIORITY_DOT: Record<string, string> = { high: "bg-slate-900", medium: "bg-slate-400", low: "bg-slate-300" };

// D7: over SLA means still open past its due_at.
const overSla = (t: RawReviewTask) => isOpen(t) && !!t.due_at && new Date(t.due_at) < new Date();

function statusBadge(t: RawReviewTask) {
  if (t.status === "escalated") {
    return (
      <div>
        <StatusBadge tone="red">ESCALATED</StatusBadge>
        {t.details?.escalation && (
          <div className="mt-0.5 text-xs text-slate-500">by {t.details.escalation.by}</div>
        )}
      </div>
    );
  }
  if (t.status === "pending") return <StatusBadge tone="gray">OPEN</StatusBadge>;
  if (t.status === "in_progress") return <StatusBadge tone="amber">IN REVIEW</StatusBadge>;
  return <StatusBadge tone="green">DONE</StatusBadge>;
}

export function ReviewQueuePage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const wantId = searchParams.get("item");
  const [tab, setTab] = useState<Tab>("all");
  const [items, setItems] = useState<RawReviewTask[]>([]);
  const [selected, setSelected] = useState<RawReviewTask | null>(null);
  const [loading, setLoading] = useState(true);
  const [deepLinkNotFound, setDeepLinkNotFound] = useState(false);
  // The list loads at most 100 rows and there is no GET-one-review-item
  // endpoint, so an ?item= id can genuinely be unreachable (closed, moved to
  // another queue, or past the first 100; the server lists open items first).
  // Try it once, not on every reload (onDone re-runs load()).
  const deepLinkHandled = useRef(false);

  function load() {
    setLoading(true);
    listReviewTasks({ limit: 100 })
      .then(r => {
        setItems(r.items);
        if (wantId && !deepLinkHandled.current) {
          deepLinkHandled.current = true;
          const found = r.items.find(t => t.id === wantId);
          if (found) setSelected(found);
          else setDeepLinkNotFound(true);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }
  // Once on mount; onDone reloads explicitly.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  function selectRow(t: RawReviewTask) {
    setSelected(t);
    setDeepLinkNotFound(false);
  }

  const overSlaCount = items.filter(overSla).length;

  const tabs = [
    { key: "all" as Tab, label: `All (${items.length})` },
    { key: "mine" as Tab, label: `Mine (${items.filter(t => t.assigned_to === user?.id).length})` },
    { key: "high" as Tab, label: `High priority (${items.filter(t => t.priority === "high").length})` },
    { key: "sla" as Tab, label: `Over SLA (${overSlaCount})` },
  ];
  const filtered = items.filter(t =>
    tab === "mine" ? t.assigned_to === user?.id
    : tab === "high" ? t.priority === "high"
    : tab === "sla" ? overSla(t)
    : true
  );

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Administrative review queue</h1>
          <p className="mt-1 text-sm text-slate-500">{items.length} cases • {overSlaCount} over SLA</p>
        </div>
        <div className="flex gap-3">
          <button className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"><Download className="h-4 w-4" />Export</button>
          <button onClick={() => navigate("/review-queue/add")} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover">Add case</button>
        </div>
      </div>
      {deepLinkNotFound && (
        <div role="alert" className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          That review item is not in this list: it may be closed or moved to another queue.
        </div>
      )}
      <div className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div className="flex gap-6 border-b border-slate-200 px-6 text-sm">
          {tabs.map(t => <button key={t.key} onClick={() => setTab(t.key)} className={`py-3 font-medium ${tab === t.key ? "border-b-2 border-brand text-slate-900" : "text-slate-500 hover:text-slate-700"}`}>{t.label}</button>)}
        </div>
        {loading ? <div className="p-8"><Spinner /></div> : (
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">{["Case", "Submitted", "Type", "Patient", "Channel", "Priority", "Owner", "Status"].map(h => <th key={h} className="px-6 py-3">{h}</th>)}</tr></thead>
            <tbody>
              {filtered.length === 0 ? <tr><td colSpan={8} className="px-6 py-8 text-sm text-slate-500">No cases in this queue.</td></tr>
              : filtered.map(t => (
                <tr key={t.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                  <td className="px-6 py-4 max-w-xs">
                    <button onClick={() => selectRow(t)} className="font-medium text-brand hover:underline">C-{t.case_id.slice(0, 8)}</button>
                    {t.contact_reason && <div className="mt-0.5 truncate text-xs text-slate-500" title={t.contact_reason}>{t.contact_reason}</div>}
                  </td>
                  <td className="px-6 py-4 text-slate-600">{new Date(t.created_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</td>
                  <td className="px-6 py-4 text-slate-700">{KIND_LABEL[t.task_type] ?? t.task_type}</td>
                  <td className="px-6 py-4 text-slate-700">{t.patient_name ?? "Unidentified"}</td>
                  <td className="px-6 py-4 text-slate-700 capitalize">{t.channel ?? "-"}</td>
                  <td className="px-6 py-4"><div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${PRIORITY_DOT[t.priority]}`} /><span className="capitalize text-slate-700">{t.priority}</span></div></td>
                  <td className="px-6 py-4 text-slate-700">{t.owner_label ?? "-"}</td>
                  <td className="px-6 py-4">{statusBadge(t)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {selected && <ReviewQueueDetailModal item={selected} onClose={() => setSelected(null)} onDone={() => { setSelected(null); load(); }} />}
    </div>
  );
}
