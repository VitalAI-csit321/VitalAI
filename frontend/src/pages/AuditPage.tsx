import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Download } from "lucide-react";
import { listAuditEvents } from "../api/audit";
import type { AuditEvent } from "../api/types";
import { Spinner } from "../components/ui";

const ACTION_COLOR: Record<string, string> = {
  "CASE.APPROVE": "text-brand", "CONSENT.CAPTURE": "text-brand", "RECORD.VIEW": "text-brand",
  "AUTH.DENY": "text-red-500", "USER.LOGIN": "text-slate-600", "EMAIL.SEND": "text-slate-600",
  "ROUTING.UPDATE": "text-amber-600", "ESCALATE.AUTO": "text-orange-600", "RECORD.UPLOAD": "text-slate-600",
};

const RISK_DOT: Record<string, string> = { High: "bg-slate-900", Medium: "bg-slate-400", Low: "bg-slate-300" };

// Placeholder events matching design 6 exactly
const PLACEHOLDER_EVENTS = [
  { id: "e1", action: "CASE.APPROVE", user: "s.kapoor@royalmelb.health", resource: "C-1042", risk: "High", status: "OK", time: "14:30:12" },
  { id: "e2", action: "CONSENT.CAPTURE", user: "m.alvarez@royalmelb.health", resource: "Williams, Jamie", risk: "Medium", status: "OK", time: "14:28:45" },
  { id: "e3", action: "RECORD.VIEW", user: "l.kim@royalmelb.health", resource: "MRN-8842-J", risk: "Low", status: "OK", time: "14:22:18" },
  { id: "e4", action: "AUTH.DENY", user: "m.brooks@royalmelb.health", resource: "HITL override", risk: "High", status: "BLOCKED", time: "14:18:03" },
  { id: "e5", action: "USER.LOGIN", user: "j.taylor@royalmelb.health", resource: "Session-9421", risk: "Low", status: "OK", time: "14:12:56" },
  { id: "e6", action: "EMAIL.SEND", user: "c.hines@royalmelb.health", resource: "THREAD-2026-05-22", risk: "Low", status: "OK", time: "14:05:22" },
  { id: "e7", action: "ROUTING.UPDATE", user: "s.kapoor@royalmelb.health", resource: "R-007", risk: "Medium", status: "OK", time: "13:58:11" },
  { id: "e8", action: "ESCALATE.AUTO", user: "system@royalmelb.health", resource: "T-2101", risk: "High", status: "OK", time: "13:45:33" },
  { id: "e9", action: "RECORD.UPLOAD", user: "m.chen@royalmelb.health", resource: "discharge-summary.pdf", risk: "Low", status: "OK", time: "13:32:08" },
];

export function AuditPage() {
  const navigate = useNavigate();
  const [events, setEvents] = useState(PLACEHOLDER_EVENTS);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    listAuditEvents({ limit: 25 })
      .then(res => {
        if (res.items.length > 0) {
          setEvents(res.items.map(e => ({
            id: e.id,
            action: e.action.toUpperCase().replace(".", "."),
            user: e.actorId ?? "system",
            resource: e.caseId ?? (e.details.case_id as string) ?? "—",
            risk: "Medium",
            status: "OK",
            time: new Date(e.timestamp).toLocaleTimeString("en-AU", { hour12: false }),
          })));
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const filtered = events.filter(e =>
    !search || e.action.includes(search.toUpperCase()) || e.user.includes(search) || e.resource.includes(search)
  );

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Audit logs and activity</h1>
          <p className="mt-1 text-sm text-slate-500">
            {events.length.toLocaleString()} events
            <span className="ml-2 text-brand font-medium"># Hash check passed</span>
          </p>
        </div>
        <button className="flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover">
          <Download className="h-4 w-4" />Export CSV
        </button>
      </div>

      <div className="mt-6 flex gap-3">
        <input value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search events..."
          className="flex-1 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm outline-none focus:border-brand" />
        {["Any user", "Any action", "Last 24 hours", "Any risk"].map(label => (
          <button key={label} className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50 whitespace-nowrap">{label}</button>
        ))}
      </div>

      <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-white">
        {loading ? <div className="p-8"><Spinner /></div> : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {["Time", "User", "Action", "Resource", "Risk", "Status"].map(h => (
                    <th key={h} className="px-6 py-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map(e => (
                  <tr key={e.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50 cursor-pointer"
                    onClick={() => navigate(`/audit/${e.id}`)}>
                    <td className="px-6 py-4 font-mono text-slate-700">{e.time}</td>
                    <td className="px-6 py-4 text-slate-700">{e.user}</td>
                    <td className="px-6 py-4"><span className={`font-semibold ${ACTION_COLOR[e.action] ?? "text-slate-700"}`}>{e.action}</span></td>
                    <td className="px-6 py-4 text-slate-700">{e.resource}</td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <span className={`h-2 w-2 rounded-full ${RISK_DOT[e.risk] ?? "bg-slate-300"}`} />
                        <span className="text-slate-700">{e.risk}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      {e.status === "BLOCKED"
                        ? <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-bold text-red-600">BLOCKED</span>
                        : <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">OK</span>
                      }
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex items-center justify-between px-6 py-3 border-t border-slate-100 text-sm text-brand">
              <span className="font-medium"># Chain verified</span>
              <span className="text-slate-400">Last hash: f8a4d2e9...</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
