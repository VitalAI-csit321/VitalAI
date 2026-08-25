import { useParams } from "react-router-dom";
import { useEffect, useState } from "react";
import { getAuditEvent, getAuditForCase, verifyAuditChain } from "../api/audit";
import type { AuditEvent } from "../api/types";
import { Spinner } from "../components/ui";

export function AuditEventDetailPage() {
  const { eventId } = useParams<{ eventId: string }>();
  const [event, setEvent] = useState<AuditEvent | null>(null);
  const [related, setRelated] = useState<AuditEvent[]>([]);
  const [verifyResult, setVerifyResult] = useState<{ valid: boolean; checkedCount: number } | null>(null);
  const [verifying, setVerifying] = useState(false);

  useEffect(() => {
    if (!eventId) return;
    setEvent(null);
    getAuditEvent(eventId)
      .then((e) => {
        setEvent(e);
        if (e.caseId) {
          getAuditForCase(e.caseId)
            .then((events) => setRelated(events.filter((r) => r.id !== e.id).slice(0, 5)))
            .catch(() => {});
        }
      })
      .catch(() => {});
  }, [eventId]);

  const handleVerify = () => {
    setVerifying(true);
    verifyAuditChain()
      .then((res) => setVerifyResult({ valid: res.valid, checkedCount: res.checkedCount }))
      .catch(() => setVerifyResult(null))
      .finally(() => setVerifying(false));
  };

  const fmtTime = (iso: string) => new Date(iso).toLocaleTimeString("en-AU", { hour12: false });

  if (!event) {
    return <div className="p-6"><Spinner /></div>;
  }

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Audit event: {fmtTime(event.timestamp)}</h1>
          <p className="mt-1 text-sm text-slate-500">{event.action} • Ref: {event.caseId ?? "—"}</p>
        </div>
        <div className="flex gap-2">
          <span
            className={`rounded px-2.5 py-1 text-xs font-bold ${
              event.riskLevel === "High" ? "bg-red-100 text-red-600" : "bg-slate-100 text-slate-600"
            }`}
          >
            {event.riskLevel.toUpperCase()} RISK
          </span>
          <span
            className={`rounded px-2.5 py-1 text-xs font-bold ${
              event.outcome === "BLOCKED" ? "bg-red-100 text-red-600" : "bg-slate-100 text-slate-600"
            }`}
          >
            {event.outcome ?? "—"}
          </span>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1.5fr_1fr]">
        <div className="rounded-xl border border-slate-200 bg-white p-6">
          <h2 className="text-base font-semibold text-slate-900 mb-5">Event summary</h2>
          <div className="grid grid-cols-2 gap-4 text-sm mb-5">
            {[
              ["Time", fmtTime(event.timestamp)],
              ["User", event.actorLabel ?? "system"],
              ["Action", event.action],
              ["Resource", event.caseId ?? "—"],
              ["IP Address", event.ipAddress ?? "—"],
              ["Session", event.sessionId ?? "—"],
              ["Outcome", event.outcome ?? "—"],
              ["Risk Level", event.riskLevel],
            ].map(([l, v]) => (
              <div key={l}>
                <div className="text-xs text-slate-500 uppercase tracking-wide">{l}</div>
                <div className="font-medium text-slate-900 mt-0.5">{v}</div>
              </div>
            ))}
          </div>

          <div>
            <p className="text-xs text-slate-500 uppercase tracking-wide mb-2">Event payload</p>
            <div className="rounded-lg bg-slate-900 p-4 font-mono text-xs overflow-auto max-h-60">
              <pre className="text-slate-300">{JSON.stringify(event.details, null, 2)}</pre>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="flex items-center gap-2 mb-4">
              <span className="text-brand text-lg">✓</span>
              <h2 className="text-base font-semibold text-brand">Tamper-evident chain</h2>
            </div>
            {event.eventHash ? (
              <div className="rounded-lg bg-emerald-50 border border-emerald-200 px-4 py-2.5 mb-4 text-sm text-emerald-700 font-medium">
                Chained
              </div>
            ) : (
              <div className="rounded-lg bg-slate-50 border border-slate-200 px-4 py-2.5 mb-4 text-sm text-slate-500 font-medium">
                Pre-chain, unverified
              </div>
            )}

            <p className="text-xs text-slate-500 uppercase tracking-wide mb-1">Event hash</p>
            <div className="rounded-lg bg-slate-900 px-3 py-2 font-mono text-xs text-slate-300 mb-3 break-all">
              {event.eventHash ?? "—"}
            </div>

            <p className="text-xs text-slate-500 uppercase tracking-wide mb-1">Predecessor hash</p>
            <div className="rounded-lg bg-slate-900 px-3 py-2 font-mono text-xs text-slate-300 mb-4 break-all">
              {event.predecessorHash ?? "—"}
            </div>

            <button
              onClick={handleVerify}
              disabled={verifying}
              className="w-full rounded-lg border border-slate-200 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 flex items-center justify-center gap-2"
            >
              {verifying ? "Verifying..." : "# Verify integrity"}
            </button>
            {verifyResult && (
              <p className={`mt-2 text-xs text-center ${verifyResult.valid ? "text-emerald-700" : "text-red-600"}`}>
                {verifyResult.valid
                  ? `Verified • ${verifyResult.checkedCount} events checked, integrity intact`
                  : "Integrity check failed - chain break detected"}
              </p>
            )}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-base font-semibold text-slate-900 mb-4">Related events</h2>
            <div className="space-y-3">
              {related.length === 0 ? (
                <p className="text-sm text-slate-500">No other events for this case.</p>
              ) : (
                related.map((e) => (
                  <div key={e.id} className="cursor-pointer hover:bg-slate-50 rounded-lg px-2 py-1 -mx-2">
                    <div className="text-sm font-semibold text-slate-900">{e.action}</div>
                    <div className="text-xs text-slate-500">{fmtTime(e.timestamp)} • {e.actorLabel ?? "system"}</div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
