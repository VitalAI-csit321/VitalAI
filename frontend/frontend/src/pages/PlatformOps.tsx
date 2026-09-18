import { useState, useEffect } from "react";
import { NavLink, Outlet, useNavigate, Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { Spinner } from "../components/ui";
import { describeApiError } from "../lib/apiClient";
import { getDetailedHealth } from "../api/platformOps";
import { listIncidents } from "../api/audit";
import { listSettings } from "../api/settings";
import { SettingsSection } from "./settings/SettingsSections";
import type { DetailedHealth, ServiceStatus, AuditEvent, AppSettingItem } from "../api/types";

// Design 12 — Platform Ops entry. The console reads live health and the
// governance incident feed, both gated on READ_AUDIT (admin only) server-side
// and on the route below. There is no separate operator credential, so this is
// a hand-off panel, not a login form that pretends to authenticate.
export function PlatformOpsLoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-xl">
        <p className="text-sm font-semibold text-slate-700 mb-1">VitalAI</p>
        <h1 className="text-2xl font-bold text-slate-900 mb-2">Platform Operations</h1>
        <p className="text-sm text-slate-500 mb-6">
          This console shows live service health and the governance incident feed. Both require an
          administrator session. You are already signed in with your VitalAI account; a non-admin
          session is sent back to the dashboard.
        </p>
        <Link
          to="/platform-ops/system-health"
          className="block w-full rounded-lg bg-brand py-2.5 text-center text-sm font-semibold text-white hover:bg-brand-hover"
        >
          Continue to the console
        </Link>
        <p className="mt-4 text-center text-xs text-slate-400">All access to this area is logged.</p>
      </div>
    </div>
  );
}

// Platform Ops shell layout (designs 13 & 14)
export function PlatformOpsLayout() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const initials = (user?.fullName ?? "?")
    .split(" ")
    .map(w => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  const navItems = [
    { to: "/platform-ops/system-health", label: "System Health", icon: "⚡" },
    { to: "/platform-ops/model-config", label: "Model and Risk Configuration", icon: "⚙" },
  ];

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="w-56 shrink-0 bg-sidebar flex flex-col text-slate-200">
        <div className="px-6 py-5 text-lg font-bold text-white">VitalAI</div>
        <button onClick={() => navigate("/dashboard")}
          className="flex items-center gap-2 px-6 py-3 text-sm text-slate-400 hover:text-white">
          ← Back to VitalAI
        </button>
        <nav className="flex-1 px-3 space-y-1 mt-2">
          {navItems.map(({ to, label, icon }) => (
            <NavLink key={to} to={to}
              className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium ${isActive ? "bg-sidebar-active text-white" : "text-slate-300 hover:bg-sidebar-hover hover:text-white"}`}>
              <span>{icon}</span>{label}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center gap-3 border-t border-white/10 px-4 py-4">
          <div className="h-9 w-9 rounded-full bg-brand flex items-center justify-center text-sm font-semibold text-white">{initials}</div>
          <div>
            <div className="text-sm font-medium text-white">{user?.fullName ?? "Unknown"}</div>
            <div className="text-xs text-slate-400 capitalize">{user?.role ?? ""}</div>
          </div>
        </div>
      </aside>
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex items-center justify-between bg-slate-900 px-6 py-2.5 text-sm text-white">
          <span>Platform Operations Mode. All actions logged{user ? `. ${user.fullName}` : ""}</span>
          <button onClick={() => navigate("/dashboard")}
            className="rounded-lg border border-slate-600 px-3 py-1 text-sm text-white hover:bg-slate-700">
            Exit Operations
          </button>
        </div>
        <main className="flex-1 overflow-y-auto bg-white">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

// Design 13 — System Health, on real data from GET /health/detailed and
// GET /audit/incidents.
const STATUS_DOT: Record<ServiceStatus["status"], string> = {
  operational: "bg-emerald-500",
  degraded: "bg-amber-400",
  down: "bg-red-500",
  disabled: "bg-slate-400",
};
const STATUS_TEXT: Record<ServiceStatus["status"], string> = {
  operational: "text-emerald-600",
  degraded: "text-amber-600",
  down: "text-red-600",
  disabled: "text-slate-500",
};
const STATUS_LABEL: Record<ServiceStatus["status"], string> = {
  operational: "Operational",
  degraded: "Degraded",
  down: "Down",
  disabled: "Disabled",
};

// Worst live service wins. `disabled` is a deliberate off switch, not a fault,
// so it never drags the overall state down.
function overallStatus(services: ServiceStatus[]): ServiceStatus["status"] {
  if (services.some(s => s.status === "down")) return "down";
  if (services.some(s => s.status === "degraded")) return "degraded";
  if (services.some(s => s.status === "operational")) return "operational";
  return "disabled";
}

function formatUptime(seconds: number | null): string {
  if (seconds == null) return "unknown";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}

export function SystemHealthPage() {
  const [health, setHealth] = useState<DetailedHealth | null>(null);
  const [incidents, setIncidents] = useState<AuditEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [h, inc] = await Promise.all([getDetailedHealth(), listIncidents(20)]);
        if (!active) return;
        setHealth(h);
        setIncidents(inc);
        setUpdatedAt(new Date());
        setError(null);
      } catch (err) {
        if (active) setError(describeApiError(err, "Could not load system health."));
      }
    }
    load();
    const t = setInterval(load, 15000);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, []);

  if (error) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold text-slate-900 mb-2">System Health</h1>
        <p className="text-sm text-red-700">{error}</p>
      </div>
    );
  }
  if (!health || !incidents) {
    return <div className="p-6"><Spinner label="Loading system health" /></div>;
  }

  const overall = overallStatus(health.services);
  const { latency } = health;

  return (
    <div className="p-6">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">System Health</h1>
          <p className="text-sm text-slate-500">Live status of VitalAI platform services</p>
        </div>
        <div className="text-sm text-slate-500">
          {updatedAt && <span>Updated {updatedAt.toLocaleTimeString()}</span>}
          <span className="ml-3 text-slate-400">Auto-refresh 15s</span>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="rounded-xl border border-t-2 border-brand border-slate-200 bg-white p-5">
          <div className="text-xs text-slate-500 uppercase tracking-wide mb-2">Overall Status</div>
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${STATUS_DOT[overall]}`} />
            <span className={`text-2xl font-bold ${STATUS_TEXT[overall]}`}>{STATUS_LABEL[overall]}</span>
          </div>
          <div className="text-xs text-slate-500 mt-1">{health.services.length} services checked</div>
        </div>
        <div className="rounded-xl border border-t-2 border-brand border-slate-200 bg-white p-5">
          <div className="text-xs text-slate-500 uppercase tracking-wide mb-2">Uptime</div>
          <div className="text-3xl font-bold text-slate-900 mb-1">{formatUptime(health.uptimeSeconds)}</div>
          <div className="text-xs text-slate-500">Since the API process started</div>
        </div>
        <div className="rounded-xl border border-t-2 border-brand border-slate-200 bg-white p-5">
          <div className="text-xs text-slate-500 uppercase tracking-wide mb-2">Average Latency</div>
          <div className="text-3xl font-bold text-slate-900 mb-1">
            {latency.avgMs == null ? "—" : `${latency.avgMs} ms`}
          </div>
          <div className="text-xs text-slate-500">
            {latency.count === 0
              ? "No samples yet"
              : `p95 ${latency.p95Ms} ms over the last ${latency.count} requests`}
          </div>
        </div>
        <div className="rounded-xl border border-t-2 border-brand border-slate-200 bg-white p-5">
          <div className="text-xs text-slate-500 uppercase tracking-wide mb-2">Active Sessions</div>
          <div className="text-3xl font-bold text-slate-900 mb-1">{health.activeSessions}</div>
          <div className="text-xs text-slate-500">Distinct sessions, last 30 minutes</div>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white mb-6">
        <h2 className="text-base font-semibold text-slate-900 px-6 py-4 border-b border-slate-100">Services</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              {["Service", "Detail", "Status", "Latency", "Note"].map(h => (
                <th key={h} className="px-6 py-3">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {health.services.map(s => (
              <tr key={s.name} className="border-t border-slate-100 align-top">
                <td className="px-6 py-3 font-medium text-slate-900">{s.name}</td>
                <td className="px-6 py-3 text-slate-600">{s.detail}</td>
                <td className="px-6 py-3">
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${STATUS_DOT[s.status]}`} />
                    <span className={STATUS_TEXT[s.status]}>{STATUS_LABEL[s.status]}</span>
                  </div>
                </td>
                <td className="px-6 py-3 text-slate-700">{s.latencyMs == null ? "—" : `${s.latencyMs} ms`}</td>
                <td className="px-6 py-3 text-xs text-slate-500 max-w-md">{s.note ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white">
        <h2 className="text-base font-semibold text-slate-900 px-6 py-4 border-b border-slate-100">
          Recent Incidents
        </h2>
        {incidents.length === 0 ? (
          <p className="text-center text-sm text-slate-400 py-8">No governance blocks recorded.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                {["Time", "Actor", "Action", "Outcome", "Details"].map(h => (
                  <th key={h} className="px-6 py-3">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {incidents.map(i => (
                <tr key={i.id} className="border-t border-slate-100 align-top">
                  <td className="px-6 py-3 text-slate-600 font-mono text-xs whitespace-nowrap">
                    {new Date(i.timestamp).toLocaleString()}
                  </td>
                  <td className="px-6 py-3 text-slate-700">{i.actorLabel ?? "—"}</td>
                  <td className="px-6 py-3 text-slate-700">{i.action}</td>
                  <td className="px-6 py-3">
                    <span className="rounded px-2 py-0.5 text-xs font-semibold bg-red-100 text-red-600">
                      {i.outcome ?? "BLOCKED"}
                    </span>
                  </td>
                  <td className="px-6 py-3 text-xs text-slate-500 font-mono max-w-md break-all">
                    {Object.keys(i.details).length ? JSON.stringify(i.details) : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// Design 14 — Model & Risk Configuration. Both tabs bind to the Phase 2
// settings registry; there is no separate model store.
export function ModelConfigPage() {
  const [tab, setTab] = useState("Model Configuration");
  const tabs = ["Model Configuration", "Risk Tier Thresholds", "Agent Prompts"];

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-slate-900">Model and Risk Configuration</h1>
      <p className="text-sm text-slate-500 mb-6">Configure the LLM provider and risk routing thresholds</p>

      <div className="flex gap-6 border-b border-slate-200 mb-6">
        {tabs.map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`pb-3 text-sm font-medium flex items-center gap-2 ${tab === t ? "border-b-2 border-brand text-slate-900" : "text-slate-500 hover:text-slate-700"}`}>
            {t}{t === "Agent Prompts" && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">Coming soon</span>}
          </button>
        ))}
      </div>

      {tab === "Model Configuration" && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
          <SettingsSection group="Model" />
          <ActiveModelPanel />
        </div>
      )}
      {tab === "Risk Tier Thresholds" && <SettingsSection group="Approval tiers" />}
      {tab === "Agent Prompts" && (
        <p className="text-sm text-slate-500 py-8 text-center">Agent prompt editing is not available yet.</p>
      )}
    </div>
  );
}

function ActiveModelPanel() {
  const [items, setItems] = useState<AppSettingItem[] | null>(null);

  useEffect(() => {
    let active = true;
    listSettings()
      .then(res => { if (active) setItems(res); })
      .catch(() => { if (active) setItems([]); });
    return () => { active = false; };
  }, []);

  const model = items?.find(i => i.key === "llm_model");

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 h-fit">
      <h2 className="text-base font-semibold text-slate-900 mb-4">Active configuration</h2>
      {!items ? (
        <Spinner />
      ) : (
        <div className="space-y-3 text-sm">
          <div>
            <div className="text-xs text-slate-500">Current model</div>
            <span className="mt-1 inline-block rounded bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">
              {String(model?.value ?? "unknown")}
            </span>
          </div>
          <div>
            <div className="text-xs text-slate-500">Last changed</div>
            <div className="font-medium text-slate-900">
              {model?.updatedAt
                ? new Date(model.updatedAt).toLocaleString()
                : "Never — running the deployed default"}
            </div>
            {model?.updatedBy && <div className="text-xs text-slate-500">by {model.updatedBy}</div>}
          </div>
        </div>
      )}
    </div>
  );
}
