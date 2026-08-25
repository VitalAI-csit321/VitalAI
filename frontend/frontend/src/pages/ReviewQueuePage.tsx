import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Download } from "lucide-react";
import { StatusBadge, Spinner } from "../components/ui";
import { ReviewQueueDetailModal } from "./ReviewQueueDetailModal";
import { listReviewTasks, claimReviewTask, completeReviewTask, rejectReviewTask, escalateReviewTask, type RawReviewTask } from "../api/reviewTasks";
import { useAuth } from "../lib/auth";

type Tab = "all" | "mine" | "high" | "sla";
interface QueueCase { id: string; caseRef: string; submitted: string; type: string; priority: RawReviewTask["priority"]; owner: string; reviewed: boolean; status: "open"|"review"|"done"; assignedTo: string | null; rawStatus: RawReviewTask["status"]; notes: string | null; }

const PRIORITY_DOT: Record<string,string> = { high:"bg-slate-900", medium:"bg-slate-400", low:"bg-slate-300" };
const STATUS_TONE = { open:"gray" as const, review:"amber" as const, done:"green" as const };
const TYPE_LABEL: Record<string,string> = { triage_review:"Triage review", consent_review:"Consent review", escalation_review:"Escalation review" };

function toCase(t: RawReviewTask): QueueCase {
  const statusMap: Record<string,QueueCase["status"]> = { pending:"open", in_progress:"review", completed:"done", cancelled:"done", escalated:"review" };
  return {
    id: t.id, caseRef: `C-${t.case_id.slice(0,8)}`,
    submitted: new Date(t.created_at).toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric"}),
    type: TYPE_LABEL[t.task_type] ?? t.task_type,
    priority: t.priority,
    owner: t.assigned_to ? `user-${t.assigned_to.slice(0,8)}` : "Unassigned",
    reviewed: t.status==="completed",
    status: statusMap[t.status] ?? "open",
    assignedTo: t.assigned_to,
    rawStatus: t.status,
    notes: t.notes,
  };
}

export function ReviewQueuePage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [tab,setTab] = useState<Tab>("all");
  const [cases,setCases] = useState<QueueCase[]>([]);
  const [selected,setSelected] = useState<QueueCase|null>(null);
  const [loading,setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    listReviewTasks({limit:20})
      .then(r => setCases(r.items.map(toCase)))
      .catch(()=>{}).finally(()=>setLoading(false));
  }
  useEffect(()=>{ load(); },[]);

  async function handleAction(caseId: string, action: "approve"|"reject"|"escalate", notes: string) {
    const task = cases.find(c=>c.id===caseId); if(!task) return;
    setActionError(null);
    try {
      if (task.rawStatus === "pending") {
        await claimReviewTask(task.id);
      }
      if (action === "reject") {
        await rejectReviewTask(task.id, notes || null);
      } else if (action === "escalate") {
        await escalateReviewTask(task.id, notes || null);
      } else {
        await completeReviewTask(task.id, notes || null);
      }
      load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not record the decision.");
      throw e;
    }
    setSelected(null);
  }

  const tabs = [
    {key:"all" as Tab, label:`All (${cases.length})`},
    {key:"mine" as Tab, label:`Mine (${cases.filter(c=>c.assignedTo===user?.id).length})`},
    {key:"high" as Tab, label:`High priority (${cases.filter(c=>c.priority==="high").length})`},
    {key:"sla" as Tab, label:`Over SLA (${cases.filter(c=>!c.reviewed&&c.priority==="high").length})`},
  ];
  const filtered = cases.filter(c => tab==="mine"?c.assignedTo===user?.id:tab==="high"?c.priority==="high":tab==="sla"?!c.reviewed&&c.priority==="high":true);

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div><h1 className="text-2xl font-bold text-slate-900">Administrative review queue</h1><p className="mt-1 text-sm text-slate-500">{cases.length} cases • {cases.filter(c=>!c.reviewed&&c.priority==="high").length} over SLA</p></div>
        <div className="flex gap-3">
          <button className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"><Download className="h-4 w-4"/>Export</button>
          <button onClick={()=>navigate("/review-queue/add")} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover">Add case</button>
        </div>
      </div>
      <div className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div className="flex gap-6 border-b border-slate-200 px-6 text-sm">
          {tabs.map(t=><button key={t.key} onClick={()=>setTab(t.key)} className={`py-3 font-medium ${tab===t.key?"border-b-2 border-brand text-slate-900":"text-slate-500 hover:text-slate-700"}`}>{t.label}</button>)}
        </div>
        {loading?<div className="p-8"><Spinner/></div>:(
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">{["Case","Submitted","Type","Priority","Owner","Reviewed","Status"].map(h=><th key={h} className="px-6 py-3">{h}</th>)}</tr></thead>
            <tbody>
              {filtered.length===0?<tr><td colSpan={7} className="px-6 py-8 text-sm text-slate-500">No cases in this queue.</td></tr>
              :filtered.map(c=>(
                <tr key={c.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                  <td className="px-6 py-4"><button onClick={()=>setSelected(c)} className="font-medium text-brand hover:underline">{c.caseRef}</button></td>
                  <td className="px-6 py-4 text-slate-600">{c.submitted}</td>
                  <td className="px-6 py-4 text-slate-700">{c.type}</td>
                  <td className="px-6 py-4"><div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${PRIORITY_DOT[c.priority]}`}/><span className="capitalize text-slate-700">{c.priority}</span></div></td>
                  <td className="px-6 py-4 text-slate-700">{c.owner}</td>
                  <td className="px-6 py-4 text-slate-600">{c.reviewed?"Yes":"No"}</td>
                  <td className="px-6 py-4"><StatusBadge tone={STATUS_TONE[c.status]}>{c.status.toUpperCase()}</StatusBadge></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {selected&&<ReviewQueueDetailModal case_={selected} onClose={()=>setSelected(null)} onAction={handleAction} actionError={actionError}/>}
    </div>
  );
}
