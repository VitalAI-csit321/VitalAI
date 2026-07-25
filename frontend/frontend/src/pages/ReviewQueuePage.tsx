import { useState } from "react";
import { Download } from "lucide-react";
import { StatusBadge } from "../components/ui";
import { ReviewQueueDetailModal } from "./ReviewQueueDetailModal";

type Tab = "all" | "mine" | "high" | "sla";

interface QueueCase {
  id: string;
  caseRef: string;
  submitted: string;
  type: string;
  priority: "low" | "medium" | "high";
  owner: string;
  reviewed: boolean;
  status: "open" | "review" | "done";
}

const MOCK: QueueCase[] = [
  { id: "1", caseRef: "C-1042", submitted: "22 May 2026", type: "HITL approval", priority: "high", owner: "S. Kapoor", reviewed: false, status: "open" },
  { id: "2", caseRef: "C-1041", submitted: "22 May 2026", type: "Record verification", priority: "medium", owner: "M. Chen", reviewed: true, status: "review" },
  { id: "3", caseRef: "C-1039", submitted: "21 May 2026", type: "Data quality", priority: "high", owner: "S. Kapoor", reviewed: false, status: "open" },
  { id: "4", caseRef: "C-1038", submitted: "20 May 2026", type: "Policy exception", priority: "medium", owner: "J. Taylor", reviewed: true, status: "review" },
  { id: "5", caseRef: "C-1037", submitted: "20 May 2026", type: "HITL approval", priority: "high", owner: "S. Kapoor", reviewed: false, status: "open" },
  { id: "6", caseRef: "C-1036", submitted: "19 May 2026", type: "Record verification", priority: "low", owner: "M. Chen", reviewed: true, status: "done" },
];

const STATUS_TONE = { open: "gray" as const, review: "amber" as const, done: "green" as const };
const STATUS_LABEL = { open: "OPEN", review: "REVIEW", done: "DONE" };

const PRIORITY_DOT: Record<string, string> = { high: "bg-slate-900", medium: "bg-slate-400", low: "bg-slate-300" };

export function ReviewQueuePage() {
  const [tab, setTab] = useState<Tab>("all");
  const [selected, setSelected] = useState<QueueCase | null>(null);
  const cases = MOCK;

  const tabs: { key: Tab; label: string }[] = [
    { key: "all", label: `All (${cases.length})` },
    { key: "mine", label: `Mine (${cases.filter(c => c.owner === "S. Kapoor").length})` },
    { key: "high", label: `High priority (${cases.filter(c => c.priority === "high").length})` },
    { key: "sla", label: `Over SLA (${cases.filter(c => !c.reviewed && c.priority === "high").length})` },
  ];

  const filtered = cases.filter(c => {
    if (tab === "mine") return c.owner === "S. Kapoor";
    if (tab === "high") return c.priority === "high";
    if (tab === "sla") return !c.reviewed && c.priority === "high";
    return true;
  });

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Administrative review queue</h1>
          <p className="mt-1 text-sm text-slate-500">{cases.length} cases • {cases.filter(c => !c.reviewed && c.priority === "high").length} over SLA</p>
        </div>
        <div className="flex gap-3">
          <button className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
            <Download className="h-4 w-4" />Export
          </button>
          <button className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover">Add case</button>
        </div>
      </div>

      <div className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div className="flex gap-6 border-b border-slate-200 px-6 text-sm">
          {tabs.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`py-3 font-medium ${tab === t.key ? "border-b-2 border-brand text-slate-900" : "text-slate-500 hover:text-slate-700"}`}>
              {t.label}
            </button>
          ))}
        </div>

        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              {["Case", "Submitted", "Type", "Priority", "Owner", "Reviewed", "Status"].map(h => (
                <th key={h} className="px-6 py-3">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(c => (
              <tr key={c.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                <td className="px-6 py-4">
                  <button onClick={() => setSelected(c)} className="font-medium text-brand hover:underline">{c.caseRef}</button>
                </td>
                <td className="px-6 py-4 text-slate-600">{c.submitted}</td>
                <td className="px-6 py-4 text-slate-700">{c.type}</td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${PRIORITY_DOT[c.priority]}`} />
                    <span className="capitalize text-slate-700">{c.priority}</span>
                  </div>
                </td>
                <td className="px-6 py-4 text-slate-700">{c.owner}</td>
                <td className="px-6 py-4 text-slate-600">{c.reviewed ? "Yes" : "No"}</td>
                <td className="px-6 py-4">
                  <StatusBadge tone={STATUS_TONE[c.status]}>{STATUS_LABEL[c.status]}</StatusBadge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && <ReviewQueueDetailModal case_={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
