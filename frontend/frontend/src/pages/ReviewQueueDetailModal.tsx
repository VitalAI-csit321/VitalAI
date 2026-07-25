import { useState } from "react";
interface QueueCase { id:string; caseRef:string; submitted:string; type:string; priority:string; owner:string; reviewed:boolean; status:string; }

export function ReviewQueueDetailModal({ case_, onClose, onAction }:{ case_:QueueCase; onClose:()=>void; onAction:(id:string,action:"approve"|"reject"|"escalate")=>void; }) {
  const [notes,setNotes]=useState("");
  const [showConfirm,setShowConfirm]=useState<"approve"|"reject"|null>(null);
  const [confirmChecked,setConfirmChecked]=useState(false);
  const [done,setDone]=useState(false);
  const [busy,setBusy]=useState(false);

  async function act(action:"approve"|"reject"|"escalate") {
    setBusy(true); await onAction(case_.id,action); setDone(true); setBusy(false);
  }

  if(done) return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center">
      <div className="bg-white rounded-2xl p-8 max-w-sm text-center shadow-2xl">
        <div className="text-5xl mb-4">✓</div>
        <h2 className="text-lg font-bold text-slate-900">Decision recorded</h2>
        <p className="mt-2 text-sm text-slate-500">The case has been updated and the audit trail recorded.</p>
        <button onClick={onClose} className="mt-6 w-full rounded-lg bg-brand py-2.5 text-sm font-semibold text-white">Close</button>
      </div>
    </div>
  );

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose}/>
      <div className="fixed inset-0 z-40 flex items-center justify-center p-6 pointer-events-none">
        <div className="pointer-events-auto w-full max-w-5xl rounded-2xl bg-white shadow-2xl max-h-[90vh] overflow-y-auto">
          <div className="p-6">
            <div className="flex items-start justify-between">
              <div><h1 className="text-2xl font-bold text-slate-900">Case {case_.caseRef}</h1><p className="text-sm text-slate-500">HITL approval required</p></div>
              <div className="flex items-center gap-3">
                <span className="rounded bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600 uppercase">OPEN</span>
                <span className="rounded bg-red-100 px-2.5 py-1 text-xs font-semibold text-red-600">HIGH RISK</span>
                <span className="text-sm text-red-500 font-medium">⏱ SLA: 2h 15m</span>
                <button onClick={onClose} className="ml-4 text-slate-400 hover:text-slate-600 text-xl">×</button>
              </div>
            </div>
            <div className="mt-6 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
              <div className="space-y-5">
                <div className="rounded-xl border border-slate-200 p-5">
                  <h2 className="font-semibold text-slate-900 mb-4">Case information</h2>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    {[["Case ID",case_.caseRef],["Type",case_.type],["Priority",case_.priority],["Owner",case_.owner],["Submitted",case_.submitted],["Patient","Jamie Williams"]].map(([l,v])=>(
                      <div key={l}><div className="text-xs text-slate-500 uppercase tracking-wide">{l}</div><div className="font-medium text-slate-900 mt-0.5 capitalize">{v}</div></div>
                    ))}
                    <div className="col-span-2"><div className="text-xs text-slate-500 uppercase tracking-wide">Description</div><p className="mt-1 text-sm text-slate-700">Automated system flagged this consent form for human review due to multiple risk indicators. Manual verification required before proceeding.</p></div>
                  </div>
                </div>
                <div className="rounded-xl border border-slate-200 p-5">
                  <h2 className="font-semibold text-slate-900 mb-4">Timeline</h2>
                  {[{dot:"bg-brand",label:"Case created",time:`${case_.submitted}, 14:30`},{dot:"bg-amber-400",label:`Assigned to ${case_.owner}`,time:`${case_.submitted}, 14:31`},{dot:"bg-slate-300",label:"Awaiting review",time:"Current status"}].map(e=>(
                    <div key={e.label} className="flex items-start gap-3 mb-3"><span className={`mt-1.5 h-2.5 w-2.5 rounded-full shrink-0 ${e.dot}`}/><div><div className="text-sm font-medium text-slate-900">{e.label}</div><div className="text-xs text-slate-500">{e.time}</div></div></div>
                  ))}
                </div>
              </div>
              <div className="space-y-4">
                <div className="rounded-xl border border-slate-200 p-5">
                  <h2 className="font-semibold text-slate-900 mb-3">Risk Assessment</h2>
                  <div className="flex justify-between mb-1 text-sm"><span className="text-slate-600">Risk Score</span><span className="font-bold text-red-600 text-lg">91/100</span></div>
                  <div className="h-2 rounded-full bg-slate-100 mb-1"><div className="h-2 rounded-full bg-red-500 w-[91%]"/></div>
                  <p className="text-xs font-semibold text-red-600 mb-3">HIGH RISK</p>
                  {["Complex medical history detected","High-risk procedure category","Multiple consent forms submitted","Patient age factor (65+)"].map(r=><div key={r} className="flex items-center gap-2 text-sm text-slate-700 mb-1"><span className="text-red-500">•</span>{r}</div>)}
                </div>
                <div className="rounded-xl border border-slate-200 p-5">
                  <h2 className="font-semibold text-slate-900 mb-3">Decision</h2>
                  <textarea value={notes} onChange={e=>setNotes(e.target.value)} placeholder="Add decision notes..." className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-brand resize-none h-20 mb-3"/>
                  <button onClick={()=>setShowConfirm("approve")} disabled={busy} className="w-full rounded-lg bg-brand py-2.5 text-sm font-semibold text-white hover:bg-brand-hover mb-2 disabled:opacity-50">Approve</button>
                  <button onClick={()=>setShowConfirm("reject")} disabled={busy} className="w-full rounded-lg bg-red-500 py-2.5 text-sm font-semibold text-white hover:bg-red-600 mb-2 disabled:opacity-50">Reject</button>
                  <button onClick={()=>act("escalate")} disabled={busy} className="w-full rounded-lg border border-slate-200 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">Escalate</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
            <div className="flex items-center justify-between mb-4"><h2 className="text-lg font-bold text-slate-900">Human approval required</h2><button onClick={()=>setShowConfirm(null)} className="text-slate-400 hover:text-slate-600 text-xl">×</button></div>
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 mb-4 flex items-start gap-2"><span className="text-amber-500">⚠</span><div><p className="text-sm font-semibold text-amber-800">High-risk case requires manual review</p><p className="text-sm text-amber-700">This case cannot proceed without human approval.</p></div></div>
            <div className="rounded-lg bg-slate-50 p-4 space-y-2 text-sm mb-4">
              {[["Case ID",case_.caseRef],["Type",case_.type],["Risk level","HIGH"],["Patient","Jamie Williams"]].map(([l,v])=><div key={l} className="flex justify-between"><span className="text-slate-500">{l}</span><span className={`font-medium ${l==="Risk level"?"text-red-600 bg-red-100 px-2 py-0.5 rounded text-xs":"text-slate-900"}`}>{v}</span></div>)}
            </div>
            <textarea value={notes} onChange={e=>setNotes(e.target.value)} placeholder="Please provide a reason..." className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-brand resize-none h-20 mb-3"/>
            <label className="flex items-start gap-3 text-sm text-slate-700 cursor-pointer mb-4"><input type="checkbox" checked={confirmChecked} onChange={e=>setConfirmChecked(e.target.checked)} className="mt-0.5 h-4 w-4 rounded border-slate-300"/>I have reviewed the case details and understand the implications of my decision</label>
            <div className="flex gap-3">
              <button onClick={()=>setShowConfirm(null)} className="flex-1 rounded-lg bg-red-500 py-2.5 text-sm font-semibold text-white">Reject</button>
              <button onClick={()=>confirmChecked&&act(showConfirm)} disabled={!confirmChecked||busy} className="flex-1 rounded-lg bg-brand py-2.5 text-sm font-semibold text-white disabled:opacity-50">Approve decision</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
