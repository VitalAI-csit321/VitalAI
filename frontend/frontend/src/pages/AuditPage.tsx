import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Download } from "lucide-react";
import { downloadAuditCsv, listAuditEvents } from "../api/audit";
import type { AuditEvent } from "../api/types";
import { Spinner } from "../components/ui";

const RISK_DOT: Record<string, string> = { High: "bg-slate-900", Medium: "bg-slate-400", Low: "bg-slate-300" };
const ACTION_COLOR: Record<string, string> = {
  "intake.created": "text-brand", "consent.captured": "text-brand",
  "governance.access_denied": "text-red-500", "governance.input_blocked": "text-red-500",
};

const ACTION_OPTIONS = ["Any action", "intake.created", "consent.captured", "governance.access_denied", "governance.input_blocked", "triage.performed", "routing.decided"];
const RISK_OPTIONS = ["Any risk", "High", "Medium", "Low"] as const;

export function AuditPage() {
  const navigate = useNavigate();
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [latestHash, setLatestHash] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [actionFilter, setActionFilter] = useState("Any action");
  const [riskFilter, setRiskFilter] = useState<(typeof RISK_OPTIONS)[number]>("Any risk");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    listAuditEvents({
      limit: 50,
      action: actionFilter === "Any action" ? undefined : actionFilter,
      riskLevel: riskFilter === "Any risk" ? undefined : riskFilter,
    })
      .then((res) => {
        setEvents(res.items);
        setLatestHash(res.items[0]?.eventHash ?? null);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [actionFilter, riskFilter]);

  const filtered = events.filter(
    (e) =>
      !search ||
      e.action.toLowerCase().includes(search.toLowerCase()) ||
      (e.actorLabel ?? "").toLowerCase().includes(search.toLowerCase()),
  );

  const handleExportCsv = () => {
    downloadAuditCsv({
      action: actionFilter === "Any action" ? undefined : actionFilter,
      riskLevel: riskFilter === "Any risk" ? undefined : riskFilter,
    }).catch(() => {});
  };

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Audit logs and activity</h1>
          <p className="mt-1 text-sm text-slate-500">
            {events.length} events{" "}
            <span className="ml-2 text-brand font-medium">
              {latestHash ? "# Chain verified" : "# Pre-chain, unverified"}
            </span>
          </p>
        </div>
        <button
          onClick={handleExportCsv}
          className="flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover"
        >
          <Download className="h-4 w-4" />Export CSV
        </button>
      </div>
      <div className="mt-6 flex gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search events..."
          className="flex-1 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm outline-none focus:border-brand"
        />
        <select
          value={actionFilter}
          onChange={(e) => setActionFilter(e.target.value)}
          className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-700"
        >
          {ACTION_OPTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <select
          value={riskFilter}
          onChange={(e) => setRiskFilter(e.target.value as (typeof RISK_OPTIONS)[number])}
          className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-700"
        >
          {RISK_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
      </div>
      <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-white">
        {loading ? (
          <div className="p-8"><Spinner /></div>
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {["Time", "User", "Action", "Resource", "Risk", "Status"].map((h) => (
                    <th key={h} className="px-6 py-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr><td colSpan={6} className="px-6 py-8 text-sm text-slate-500">No events found.</td></tr>
                ) : (
                  filtered.map((e) => (
                    <tr
                      key={e.id}
                      className="border-b border-slate-100 last:border-0 hover:bg-slate-50 cursor-pointer"
                      onClick={() => navigate(`/audit/${e.id}`)}
                    >
                      <td className="px-6 py-4 font-mono text-slate-700">
                        {new Date(e.timestamp).toLocaleTimeString("en-AU", { hour12: false })}
                      </td>
                      <td className="px-6 py-4 text-slate-700">{e.actorLabel ?? "system"}</td>
                      <td className="px-6 py-4">
                        <span className={`font-semibold ${ACTION_COLOR[e.action] ?? "text-slate-700"}`}>
                          {e.action.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-6 py-4 font-mono text-xs text-slate-700">
                        {e.caseId ?? (e.details?.case_id as string) ?? "—"}
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2">
                          <span className={`h-2 w-2 rounded-full ${RISK_DOT[e.riskLevel]}`} />
                          <span className="text-slate-700">{e.riskLevel}</span>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        {e.outcome === "BLOCKED" ? (
                          <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-bold text-red-600">BLOCKED</span>
                        ) : (
                          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">OK</span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
            <div className="flex items-center justify-between px-6 py-3 border-t border-slate-100 text-sm text-brand">
              <span className="font-medium">{latestHash ? "# Chain verified" : "# Pre-chain, unverified"}</span>
              <span className="text-slate-400">
                {latestHash ? `Last hash: ${latestHash.slice(0, 8)}...` : "No hashed events yet"}
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
