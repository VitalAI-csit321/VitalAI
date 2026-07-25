import { useState } from "react";

interface QueueCase {
  id: string; caseRef: string; submitted: string; type: string;
  priority: string; owner: string; reviewed: boolean; status: string;
}

function ApprovalModal({ case_, onClose, onConfirm }: {
  case_: QueueCase;
  onClose: () => void;
  onConfirm: (notes: string) => void;
}) {
  const [notes, setNotes] = useState("");
  const [checked, setChecked] = useState(false);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-slate-900">Human approval required</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xl">×</button>
        </div>

        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
          <div className="flex items-start gap-2">
            <span className="text-amber-500 text-lg">⚠</span>
            <div>
              <p className="text-sm font-semibold text-amber-800">High-risk case requires manual review</p>
              <p className="mt-1 text-sm text-amber-700">This case has been automatically flagged by the system and cannot proceed without human approval.</p>
            </div>
          </div>
        </div>

        <div className="mt-4 rounded-lg bg-slate-50 p-4 space-y-3 text-sm">
          <p className="font-semibold text-slate-700">Case summary</p>
          {[
            ["Case ID", case_.caseRef],
            ["Type", case_.type],
            ["Risk level", "HIGH"],
            ["Patient", "Jamie Williams"],
            ["Submitted", `${case_.submitted}, 14:30`],
          ].map(([label, value]) => (
            <div key={label} className="flex justify-between">
              <span className="text-slate-500">{label}</span>
              <span className={`font-medium ${label === "Risk level" ? "text-red-600 bg-red-100 px-2 py-0.5 rounded text-xs" : "text-slate-900"}`}>{value}</span>
            </div>
          ))}
        </div>

        <div className="mt-4">
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">Decision notes</label>
          <textarea
            value={notes} onChange={e => setNotes(e.target.value)}
            placeholder="Please provide a reason for your decision..."
            className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-brand resize-none h-24"
          />
        </div>

        <label className="mt-3 flex items-start gap-3 text-sm text-slate-700">
          <input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand" />
          I have reviewed the case details and understand the implications of my decision
        </label>

        <div className="mt-5 flex gap-3">
          <button onClick={onClose}
            className="flex-1 rounded-lg bg-red-500 py-2.5 text-sm font-semibold text-white hover:bg-red-600">
            Reject
          </button>
          <button onClick={() => checked && onConfirm(notes)} disabled={!checked}
            className="flex-1 rounded-lg bg-brand py-2.5 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50">
            Approve decision
          </button>
        </div>
      </div>
    </div>
  );
}

export function ReviewQueueDetailModal({ case_, onClose }: { case_: QueueCase; onClose: () => void }) {
  const [notes, setNotes] = useState("");
  const [approvalAction, setApprovalAction] = useState<"approve" | "reject" | null>(null);
  const [done, setDone] = useState(false);

  const flaggedReasons = ["Complex medical history detected", "High-risk procedure category", "Multiple consent forms submitted", "Patient age factor (65+)"];

  if (done) {
    return (
      <div className="fixed inset-0 z-40 bg-black/50 flex items-center justify-center">
        <div className="bg-white rounded-2xl p-8 max-w-sm text-center shadow-2xl">
          <div className="text-5xl mb-4">✓</div>
          <h2 className="text-lg font-bold text-slate-900">Decision recorded</h2>
          <p className="mt-2 text-sm text-slate-500">The case has been updated and all stakeholders notified.</p>
          <button onClick={onClose} className="mt-6 w-full rounded-lg bg-brand py-2.5 text-sm font-semibold text-white">Close</button>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} />
      <div className="fixed inset-0 z-40 flex items-center justify-center p-6 pointer-events-none">
        <div className="pointer-events-auto w-full max-w-5xl rounded-2xl bg-white shadow-2xl overflow-hidden max-h-[90vh] overflow-y-auto">
          <div className="p-6">
            <div className="flex items-start justify-between">
              <div>
                <h1 className="text-2xl font-bold text-slate-900">Case {case_.caseRef}</h1>
                <p className="mt-1 text-sm text-slate-500">HITL approval required</p>
              </div>
              <div className="flex items-center gap-3">
                <span className="rounded bg-slate-100 px-2.5 py-1 text-xs font-semibold uppercase text-slate-600">OPEN</span>
                <span className="rounded bg-red-100 px-2.5 py-1 text-xs font-semibold text-red-600">HIGH RISK</span>
                <span className="flex items-center gap-1 text-sm text-red-500 font-medium">⏱ SLA: 2h 15m</span>
                <button onClick={onClose} className="ml-4 text-slate-400 hover:text-slate-600 text-xl">×</button>
              </div>
            </div>

            <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
              <div className="space-y-6">
                <div className="rounded-xl border border-slate-200 p-5">
                  <h2 className="text-base font-semibold text-slate-900 mb-4">Case information</h2>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    {[["Case ID", case_.caseRef], ["Type", "HITL approval"], ["Priority", "High"], ["Owner", "S. Kapoor"], ["Submitted", `${case_.submitted}, 14:30`], ["Patient", "Jamie Williams"]].map(([l, v]) => (
                      <div key={l}><span className="text-slate-500 text-xs uppercase tracking-wide">{l}</span><div className="font-medium text-slate-900 mt-0.5">{v}</div></div>
                    ))}
                    <div className="col-span-2">
                      <span className="text-slate-500 text-xs uppercase tracking-wide">Description</span>
                      <p className="mt-1 text-slate-700 text-sm">Automated system flagged this consent form for human review due to multiple risk indicators. The patient has a complex medical history and the consent involves high-risk procedures. Manual verification is required before proceeding.</p>
                    </div>
                  </div>
                </div>

                <div className="rounded-xl border border-slate-200 p-5">
                  <h2 className="text-base font-semibold text-slate-900 mb-4">Timeline</h2>
                  <div className="space-y-4">
                    {[{dot:"bg-brand",label:"Case created",time:"22 May 2026, 14:30"},{dot:"bg-amber-400",label:"Assigned to S. Kapoor",time:"22 May 2026, 14:31"},{dot:"bg-slate-300",label:"Awaiting review",time:"Current status"}].map(e => (
                      <div key={e.label} className="flex items-start gap-3">
                        <span className={`mt-1.5 h-2.5 w-2.5 rounded-full shrink-0 ${e.dot}`} />
                        <div><div className="text-sm font-medium text-slate-900">{e.label}</div><div className="text-xs text-slate-500">{e.time}</div></div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="space-y-4">
                <div className="rounded-xl border border-slate-200 p-5">
                  <h2 className="text-base font-semibold text-slate-900 mb-3">Risk Assessment</h2>
                  <div className="flex items-center justify-between text-sm mb-1"><span className="text-slate-600">Risk Score</span><span className="font-bold text-red-600 text-lg">91/100</span></div>
                  <div className="h-2 rounded-full bg-slate-100 mb-1"><div className="h-2 rounded-full bg-red-500" style={{width:"91%"}} /></div>
                  <p className="text-xs font-semibold text-red-600 mb-4">HIGH RISK</p>
                  <p className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">Flagged reasons</p>
                  <ul className="space-y-1">{flaggedReasons.map(r => <li key={r} className="flex items-center gap-2 text-sm text-slate-700"><span className="text-red-500">•</span>{r}</li>)}</ul>
                </div>

                <div className="rounded-xl border border-slate-200 p-5">
                  <h2 className="text-base font-semibold text-slate-900 mb-3">Decision</h2>
                  <label className="block text-sm font-medium text-slate-700 mb-1.5">Notes</label>
                  <textarea value={notes} onChange={e => setNotes(e.target.value)}
                    placeholder="Add decision notes..."
                    className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-brand resize-none h-24 mb-3" />
                  <button onClick={() => setApprovalAction("approve")} className="w-full rounded-lg bg-brand py-2.5 text-sm font-semibold text-white hover:bg-brand-hover mb-2">Approve</button>
                  <button onClick={() => setApprovalAction("reject")} className="w-full rounded-lg bg-red-500 py-2.5 text-sm font-semibold text-white hover:bg-red-600 mb-2">Reject</button>
                  <button className="w-full rounded-lg border border-slate-200 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Escalate</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {approvalAction && (
        <ApprovalModal case_={case_} onClose={() => setApprovalAction(null)}
          onConfirm={() => { setApprovalAction(null); setDone(true); }} />
      )}
    </>
  );
}
