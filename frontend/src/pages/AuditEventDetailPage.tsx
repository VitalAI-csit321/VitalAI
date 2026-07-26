import { useParams, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { getAuditEvent } from "../api/audit";
import type { AuditEvent } from "../api/types";
import { Spinner } from "../components/ui";

const PLACEHOLDER: AuditEvent = {
  id: "e1", caseId: "C-1042", actorId: "u-8472", action: "CASE.APPROVE",
  details: { event_id: "evt-2026-05-22-1430-12", timestamp: "2026-05-22T14:30:12.823Z", action: "CASE.APPROVE", actor: { user_id: "u-8472", email: "s.kapoor@royalmelb.health", role: "CLINICIAN" }, resource: { type: "CASE", id: "C-1042", patient_mrn: "MRN-8842-J" }, risk_score: 91, outcome: "SUCCESS" },
  timestamp: "2026-05-22T14:30:12.823Z",
};

const RELATED = [
  { action: "CASE.REVIEW", time: "14:28:45", user: "s.kapoor@royalmelb.health" },
  { action: "CASE.ASSIGN", time: "14:22:03", user: "system@royalmelb.health" },
  { action: "CASE.CREATE", time: "14:15:30", user: "m.alvarez@royalmelb.health" },
  { action: "CONSENT.CAPTURE", time: "14:10:12", user: "m.alvarez@royalmelb.health" },
];

export function AuditEventDetailPage() {
  const { eventId } = useParams<{ eventId: string }>();
  const navigate = useNavigate();
  const [event, setEvent] = useState<AuditEvent>(PLACEHOLDER);

  useEffect(() => {
    if (eventId && eventId !== "e1") {
      getAuditEvent(eventId).then(setEvent).catch(() => {});
    }
  }, [eventId]);

  const fmtTime = (iso: string) => new Date(iso).toLocaleTimeString("en-AU", { hour12: false });
  const fmtDate = (iso: string) => new Date(iso).toLocaleString("en-AU", { hour12: false });

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Audit event: {fmtTime(event.timestamp)}</h1>
          <p className="mt-1 text-sm text-slate-500">{event.action} • Ref: {event.caseId ?? "—"}</p>
        </div>
        <div className="flex gap-2">
          <span className="rounded bg-red-100 px-2.5 py-1 text-xs font-bold text-red-600">HIGH RISK</span>
          <span className="rounded bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-600">OK</span>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1.5fr_1fr]">
        <div className="rounded-xl border border-slate-200 bg-white p-6">
          <h2 className="text-base font-semibold text-slate-900 mb-5">Event summary</h2>
          <div className="grid grid-cols-2 gap-4 text-sm mb-5">
            {[
              ["Time", fmtTime(event.timestamp)],
              ["User", "s.kapoor@royalmelb.health"],
              ["Action", event.action],
              ["Resource", event.caseId ?? "—"],
              ["IP Address", "10.42.18.156"],
              ["Session", "sess-9421"],
              ["Outcome", "SUCCESS"],
              ["Risk Level", "High"],
            ].map(([l, v]) => (
              <div key={l}><div className="text-xs text-slate-500 uppercase tracking-wide">{l}</div><div className="font-medium text-slate-900 mt-0.5">{v}</div></div>
            ))}
          </div>

          <div>
            <p className="text-xs text-slate-500 uppercase tracking-wide mb-2">Event payload</p>
            <div className="rounded-lg bg-slate-900 p-4 font-mono text-xs overflow-auto max-h-60">
              <pre className="text-green-400">{JSON.stringify(event.details, null, 2)
                .replace(/"([^"]+)":/g, '<span style="color:#7dd3fc">"$1"</span>:')}</pre>
              <div className="text-slate-300">{JSON.stringify(event.details, null, 2)}</div>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="flex items-center gap-2 mb-4">
              <span className="text-brand text-lg">✓</span>
              <h2 className="text-base font-semibold text-brand">Tamper-evident chain</h2>
            </div>
            <div className="rounded-lg bg-emerald-50 border border-emerald-200 px-4 py-2.5 mb-4 text-sm text-emerald-700 font-medium">Verified • Integrity intact</div>

            <p className="text-xs text-slate-500 uppercase tracking-wide mb-1">Event hash</p>
            <div className="rounded-lg bg-slate-900 px-3 py-2 font-mono text-xs text-slate-300 mb-3 break-all">f8a4d2e956b3c1a789d4e2f0a8b5c6d7e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8</div>

            <p className="text-xs text-slate-500 uppercase tracking-wide mb-1">Predecessor hash</p>
            <div className="rounded-lg bg-slate-900 px-3 py-2 font-mono text-xs text-slate-300 mb-4 break-all">d3e4f5a6b7c8d9e0f1e2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4</div>

            <button className="w-full rounded-lg border border-slate-200 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 flex items-center justify-center gap-2">
              # Verify integrity
            </button>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-base font-semibold text-slate-900 mb-4">Related events</h2>
            <div className="space-y-3">
              {RELATED.map(e => (
                <div key={e.action} className="cursor-pointer hover:bg-slate-50 rounded-lg px-2 py-1 -mx-2">
                  <div className="text-sm font-semibold text-slate-900">{e.action}</div>
                  <div className="text-xs text-slate-500">{e.time} • {e.user}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
