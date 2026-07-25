import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { apiGet, apiPatch } from "../lib/apiClient";
import { StatusBadge, Spinner } from "../components/ui";
import { ReviewQueueDetailModal } from "./ReviewQueueDetailModal";

type Tab = "all" | "mine" | "high" | "sla";
interface QueueCase { id: string; caseRef: string; submitted: string; type: string; priority: "low"|"medium"|"high"; owner: string; reviewed: boolean; status: "open"|"review"|"done"; }
interface RawTask { id: string; task_type: string; status: string; created_at: string; }

const PRIORITY_DOT: Record<string,string> = { high:"bg-slate-900", medium:"bg-slate-400", low:"bg-slate-300" };
const STATUS_TONE = { open:"gray" as const, review:"amber" as const, done:"green" as const };
const TYPE_LABEL: Record<string,string> = { triage_review:"HITL approval", consent_review:"Record verification", escalation_review:"Data quality" };

function toCase(t: RawTask, i: number): QueueCase {
  const pri = (["high","medium","high","medium","high","low"] as const)[i%6];
  const owners = ["S. Kapoor","M. Chen","S. Kapoor","J. Taylor","S. Kapoor","M. Chen"];
  const statusMap: Record<string,QueueCase["status"]> = { pending:"open", in_progress:"review", completed:"done", cancelled:"done" };
  return { id:t.id, caseRef:`C-${1042-i}`, submitted:new Date(t.created_at).toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric"}), type:TYPE_LABEL[t.task_type]??t.task_type, priority:pri, owner:owners[i%6], reviewed:t.status==="completed", status:statusMap[t.status]??"open" };
}

export function ReviewQueuePage() {
  const [tab,setTab] = useState<Tab>("all");
  const [cases,setCases] = useState<QueueCase[]>([]);
  const [selected,setSelected] = useState<QueueCase|null>(null);
  const [loading,setLoading] = useState(true);

  function load() {
    setLoading(true);
    apiGet<{items:RawTask[]}>("/api/v1/review-tasks?limit=20")
      .then(r => setCases(r.items.map((t,i) => toCase(t,i))))
      .catch(()=>{}).finally(()=>setLoading(false));
  }
  useEffect(()=>{ load(); },[]);

  async function handleAction(caseId: string, action: "approve"|"reject"|"escalate") {
    const task = cases.find(c=>c.id===caseId); if(!task) return;
    const statusMap = { approve:"completed", reject:"cancelled", escalate:"in_progress" };
    try { await apiPatch(`/api/v1/review-tasks/${task.id}`,{status:statusMap[action]}); } catch {}
    setCases(prev => prev.map(c => c.id===caseId ? {...c, status:action==="escalate"?"review":"done", reviewed:true} : c));
    setSelected(null);
  }

  const tabs = [
    {key:"all" as Tab, label:`All (${cases.length})`},
    {key:"mine" as Tab, label:`Mine (${cases.filter(c=>c.owner==="S. Kapoor").length})`},
    {key:"high" as Tab, label:`High priority (${cases.filter(c=>c.priority==="high").length})`},
    {key:"sla" as Tab, label:`Over SLA (${cases.filter(c=>!c.reviewed&&c.priority==="high").length})`},
  ];
  const filtered = cases.filter(c => tab==="mine"?c.owner==="S. Kapoor":tab==="high"?c.priority==="high":tab==="sla"?!c.reviewed&&c.priority==="high":true);

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div><h1 className="text-2xl font-bold text-slate-900">Administrative review queue</h1><p className="mt-1 text-sm text-slate-500">{cases.length} cases • {cases.filter(c=>!c.reviewed&&c.priority==="high").length} over SLA</p></div>
        <div className="flex gap-3">
          <button className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"><Download className="h-4 w-4"/>Export</button>
          <button className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover">Add case</button>
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
      {selected&&<ReviewQueueDetailModal case_={selected} onClose={()=>setSelected(null)} onAction={handleAction}/>}
    </div>
  );
}
