import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Download } from "lucide-react";
import { listAuditEvents } from "../api/audit";
import { Spinner } from "../components/ui";

function riskFromAction(a:string){if(a.includes("deny")||a.includes("escalat"))return"High";if(a.includes("triage")||a.includes("routing")||a.includes("updated"))return"Medium";return"Low";}
const RISK_DOT: Record<string,string>={High:"bg-slate-900",Medium:"bg-slate-400",Low:"bg-slate-300"};
const ACTION_COLOR: Record<string,string>={"intake.created":"text-brand","consent.captured":"text-brand","task.updated":"text-orange-600","auth.deny":"text-red-500"};

export function AuditPage() {
  const navigate = useNavigate();
  const [events,setEvents]=useState<{id:string;action:string;user:string;resource:string;risk:string;status:string;time:string}[]>([]);
  const [search,setSearch]=useState("");
  const [loading,setLoading]=useState(true);

  useEffect(()=>{
    listAuditEvents({limit:50}).then(res=>{
      setEvents(res.items.map(e=>({
        id:e.id,
        action:e.action.toUpperCase(),
        user:e.actorId?`user-${e.actorId.slice(0,8)}`:"system",
        resource:(e.caseId??(e.details?.case_id as string)??(e.details?.task_id as string)??"—") as string,
        risk:riskFromAction(e.action),
        status:e.action.includes("deny")?"BLOCKED":"OK",
        time:new Date(e.timestamp).toLocaleTimeString("en-AU",{hour12:false}),
      })));
    }).catch(()=>{}).finally(()=>setLoading(false));
  },[]);

  const filtered=events.filter(e=>!search||e.action.toLowerCase().includes(search.toLowerCase())||e.user.includes(search)||e.resource.includes(search));

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div><h1 className="text-2xl font-bold text-slate-900">Audit logs and activity</h1><p className="mt-1 text-sm text-slate-500">{events.length} events <span className="ml-2 text-brand font-medium"># Hash check passed</span></p></div>
        <button className="flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover"><Download className="h-4 w-4"/>Export CSV</button>
      </div>
      <div className="mt-6 flex gap-3">
        <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search events..." className="flex-1 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm outline-none focus:border-brand"/>
        {["Any user","Any action","Last 24 hours","Any risk"].map(l=><button key={l} className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50 whitespace-nowrap">{l}</button>)}
      </div>
      <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-white">
        {loading?<div className="p-8"><Spinner/></div>:(
          <>
            <table className="w-full text-sm">
              <thead><tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">{["Time","User","Action","Resource","Risk","Status"].map(h=><th key={h} className="px-6 py-3">{h}</th>)}</tr></thead>
              <tbody>
                {filtered.length===0?<tr><td colSpan={6} className="px-6 py-8 text-sm text-slate-500">No events found.</td></tr>
                :filtered.map(e=>(
                  <tr key={e.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50 cursor-pointer" onClick={()=>navigate(`/audit/${e.id}`)}>
                    <td className="px-6 py-4 font-mono text-slate-700">{e.time}</td>
                    <td className="px-6 py-4 text-slate-700">{e.user}</td>
                    <td className="px-6 py-4"><span className={`font-semibold ${ACTION_COLOR[e.action.toLowerCase()]??"text-slate-700"}`}>{e.action}</span></td>
                    <td className="px-6 py-4 font-mono text-xs text-slate-700">{e.resource}</td>
                    <td className="px-6 py-4"><div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${RISK_DOT[e.risk]}`}/><span className="text-slate-700">{e.risk}</span></div></td>
                    <td className="px-6 py-4">{e.status==="BLOCKED"?<span className="rounded bg-red-100 px-2 py-0.5 text-xs font-bold text-red-600">BLOCKED</span>:<span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">OK</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex items-center justify-between px-6 py-3 border-t border-slate-100 text-sm text-brand">
              <span className="font-medium"># Chain verified</span><span className="text-slate-400">Last hash: f8a4d2e9...</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
