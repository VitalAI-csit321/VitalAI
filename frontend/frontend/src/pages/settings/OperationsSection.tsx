import { useEffect, useState } from "react";
import { formatDateTime, formatTime } from "../../lib/format";
import { Link } from "react-router-dom";
import { listIncidents } from "../../api/audit";
import { getDetailedHealth } from "../../api/platformOps";
import type { AuditEvent, DetailedHealth, ServiceStatus } from "../../api/types";
import { roleLabel } from "../../lib/roles";
import { Spinner } from "../../components/ui";
import { describeApiError } from "../../lib/apiClient";
import { timeAgo } from "../../lib/time";

// Live service health (GET /health/detailed) and blocked requests
// (GET /audit/incidents), both read_audit. Refreshes every 15 seconds.
const REFRESH_MS = 15_000;
const PAGE = 20;

const STATUS: Record<ServiceStatus["status"], { dot: string; text: string; label: string }> = {
  operational: { dot: "bg-emerald-500", text: "text-emerald-700", label: "Operational" },
  degraded: { dot: "bg-amber-500", text: "text-amber-700", label: "Degraded" },
  down: { dot: "bg-red-500", text: "text-red-700", label: "Down" },
  disabled: { dot: "bg-slate-400", text: "text-slate-600", label: "Off" },
};

// `disabled` is a deliberate off switch, not a fault, so it never counts against.
function summary(services: ServiceStatus[]): { tone: ServiceStatus["status"]; text: string } {
  const down = services.filter(s => s.status === "down").length;
  const degraded = services.filter(s => s.status === "degraded").length;
  if (down) return { tone: "down", text: `${down} ${down === 1 ? "service is" : "services are"} down` };
  if (degraded) return { tone: "degraded", text: `${degraded} ${degraded === 1 ? "service is" : "services are"} degraded` };
  return { tone: "operational", text: "All systems operational" };
}

function formatUptime(seconds: number | null): string {
  if (seconds == null) return "Unknown";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return m ? `${m}m` : "Under a minute";
}


const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

const AREA: Record<string, string> = {
  view_queue: "the work queues",
  read_audit: "the audit log",
  manage_users: "user management",
  view_clinical: "clinical records",
  upload_clinical: "clinical document upload",
  capture_consent: "consent capture",
  configure_governance: "system settings",
};
const area = (p: string) => AREA[p] ?? p.replace(/_/g, " ");

function describe(e: AuditEvent): string {
  const d = e.details;
  if (e.action === "governance.input_blocked") return "Message blocked by the safety filter";
  if (e.action === "governance.access_denied") {
    const perms = d.kind === "any_permission" ? (d.permissions as string[]) : [d.permission as string];
    return `Refused access to ${area(perms[0])}`;
  }
  return e.action;
}

export function OperationsSection() {
  const [health, setHealth] = useState<DetailedHealth | null>(null);
  const [incidents, setIncidents] = useState<AuditEvent[] | null>(null);
  const [limit, setLimit] = useState(PAGE);
  const [error, setError] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [h, inc] = await Promise.all([getDetailedHealth(), listIncidents(limit)]);
        if (!active) return;
        setHealth(h);
        setIncidents(inc);
        setCheckedAt(new Date());
        setError(null);
      } catch (err) {
        if (active) setError(describeApiError(err, "Could not load system status."));
      }
    }
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, [limit]);

  if (error) return <p className="text-sm text-red-700">{error}</p>;
  if (!health || !incidents) return <Spinner label="Checking services" />;

  const overall = summary(health.services);
  const { latency } = health;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className={`flex items-center gap-2.5 text-sm font-semibold ${STATUS[overall.tone].text}`}>
          <span className={`h-2.5 w-2.5 rounded-full ${STATUS[overall.tone].dot}`} aria-hidden />
          {overall.text}
        </div>
        {checkedAt && (
          <p className="text-xs text-slate-500">
            Checked at {formatTime(checkedAt)}, refreshes every 15 seconds
          </p>
        )}
      </div>

      <dl className="grid grid-cols-1 divide-y divide-slate-200 rounded-xl border border-slate-200 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        <div className="px-5 py-4">
          <dt className="text-sm text-slate-500">Uptime</dt>
          <dd className="mt-1 text-xl font-semibold text-slate-900">{formatUptime(health.uptimeSeconds)}</dd>
          <dd className="text-xs text-slate-500">Since the server last started</dd>
        </div>
        <div className="px-5 py-4">
          <dt className="text-sm text-slate-500">Response time</dt>
          <dd className="mt-1 text-xl font-semibold text-slate-900">
            {latency.avgMs == null ? "No data" : `${Math.round(latency.avgMs)} ms`}
          </dd>
          <dd className="text-xs text-slate-500">
            {latency.count === 0 ? "No requests yet" : `Average; 95% under ${Math.round(latency.p95Ms ?? 0)} ms (last ${latency.count} requests)`}
          </dd>
        </div>
        <div className="px-5 py-4">
          <dt className="text-sm text-slate-500">Signed-in users</dt>
          <dd className="mt-1 text-xl font-semibold text-slate-900">{health.activeSessions}</dd>
          <dd className="text-xs text-slate-500">Active in the last 30 minutes</dd>
        </div>
      </dl>

      <section>
        <h3 className="mb-3 text-sm font-semibold text-slate-900">Services</h3>
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-medium text-slate-500">
              <tr>
                <th scope="col" className="px-4 py-2.5">Service</th>
                <th scope="col" className="px-4 py-2.5">Status</th>
                <th scope="col" className="px-4 py-2.5 text-right">Response</th>
                <th scope="col" className="px-4 py-2.5">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {health.services.map(s => (
                <tr key={s.name}>
                  <td className="px-4 py-3 font-medium text-slate-900">{s.name}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center gap-2 ${STATUS[s.status].text}`}>
                      <span className={`h-2 w-2 rounded-full ${STATUS[s.status].dot}`} aria-hidden />
                      {STATUS[s.status].label}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-slate-700">
                    {s.latencyMs == null ? "" : `${s.latencyMs} ms`}
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {s.detail}
                    {s.note && <span className="block text-xs text-slate-500">{s.note}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-baseline justify-between">
          <h3 className="text-sm font-semibold text-slate-900">Blocked requests</h3>
          <Link to="/audit" className="text-sm font-medium text-brand hover:underline">Open audit log</Link>
        </div>
        {incidents.length === 0 ? (
          <p className="rounded-xl border border-slate-200 px-4 py-6 text-center text-sm text-slate-500">
            Nothing has been blocked.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs font-medium text-slate-500">
                <tr>
                  <th scope="col" className="px-4 py-2.5">When</th>
                  <th scope="col" className="px-4 py-2.5">Who</th>
                  <th scope="col" className="px-4 py-2.5">What happened</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {incidents.map(e => (
                  <tr key={e.id} className="hover:bg-slate-50">
                    <td className="whitespace-nowrap px-4 py-3 text-slate-600">
                      <time dateTime={e.timestamp} title={formatDateTime(e.timestamp)}>{capitalise(timeAgo(e.timestamp))}</time>
                    </td>
                    <td className="px-4 py-3">
                      <span className="block text-slate-900">{e.actorLabel ?? "Unknown user"}</span>
                      {e.actorRole && <span className="text-xs text-slate-500">{roleLabel(e.actorRole)}</span>}
                    </td>
                    <td className="px-4 py-3">
                      <Link to={`/audit/${e.id}`} className="text-slate-900 hover:text-brand hover:underline">{describe(e)}</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {/* The endpoint serves at most 100; the audit log has the rest. */}
        {incidents.length === limit && limit < 100 && (
          <button onClick={() => setLimit(l => l + PAGE)}
            className="mt-3 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
            Show more
          </button>
        )}
      </section>
    </div>
  );
}
