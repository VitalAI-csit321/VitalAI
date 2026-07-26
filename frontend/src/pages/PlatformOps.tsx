import { useState, useEffect } from "react";
import { useNavigate, NavLink, Outlet, Routes, Route } from "react-router-dom";
import { useAuth } from "../lib/auth";

// Design 12 — Platform Ops login gate
export function PlatformOpsLoginPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [email, setEmail] = useState("operator@vitalai.health");
  const [password, setPassword] = useState("••••••••");
  const [mfa, setMfa] = useState("");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    navigate("/platform-ops/system-health");
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <div className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-xl">
        <p className="text-sm font-semibold text-slate-700 mb-1">VitalAI</p>
        <h1 className="text-2xl font-bold text-slate-900 mb-2">Platform Operations Access</h1>
        <p className="text-sm text-slate-500 mb-6">This area is restricted to authorised platform operators. Sign in with your operator credentials to continue.</p>
        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-bold text-brand uppercase tracking-wide mb-1">Email</label>
            <input value={email} onChange={e => setEmail(e.target.value)}
              className="w-full rounded-lg bg-slate-100 border-0 px-3.5 py-2.5 text-sm outline-none" />
          </div>
          <div>
            <label className="block text-xs font-bold text-brand uppercase tracking-wide mb-1">Password</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)}
              className="w-full rounded-lg bg-slate-100 border-0 px-3.5 py-2.5 text-sm outline-none" />
          </div>
          <div>
            <label className="block text-xs font-bold text-brand uppercase tracking-wide mb-1">MFA Code</label>
            <input value={mfa} onChange={e => setMfa(e.target.value)} placeholder="6-digit code"
              className="w-full rounded-lg bg-slate-100 border-0 px-3.5 py-2.5 text-sm outline-none" />
          </div>
          <button type="submit" className="w-full rounded-lg bg-brand py-2.5 text-sm font-semibold text-white hover:bg-brand-hover">Sign in</button>
          <p className="text-center text-xs text-slate-400">All access to this area is logged.</p>
        </form>
      </div>
    </div>
  );
}

// Platform Ops shell layout (designs 13 & 14)
export function PlatformOpsLayout() {
  const navigate = useNavigate();
  const { user } = useAuth();

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
          <div className="h-9 w-9 rounded-full bg-brand flex items-center justify-center text-sm font-semibold text-white">SK</div>
          <div><div className="text-sm font-medium text-white">Operator Name</div><div className="text-xs text-slate-400">Platform Operator</div></div>
        </div>
      </aside>
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex items-center justify-between bg-slate-900 px-6 py-2.5 text-sm text-white">
          <span>Platform Operations Mode, All actions logged. Operator: S. Kapoor</span>
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

// Design 13 — System Health
const AGENTS = [
  { name: "Intake Agent", status: "Operational", heartbeat: "2s ago", requests: 342, avgResp: "1.2s", errorRate: "0.02%" },
  { name: "Consent Agent", status: "Operational", heartbeat: "3s ago", requests: 128, avgResp: "0.9s", errorRate: "0.00%" },
  { name: "Triage Agent", status: "Operational", heartbeat: "1s ago", requests: 489, avgResp: "2.1s", errorRate: "0.04%" },
  { name: "Routing Agent", status: "Degraded", heartbeat: "12s ago", requests: 201, avgResp: "4.8s", errorRate: "0.21%" },
  { name: "Communication Agent", status: "Operational", heartbeat: "2s ago", requests: 156, avgResp: "1.4s", errorRate: "0.01%" },
];

const INFRA = [
  { name: "Database", detail: "PostgreSQL RDS", status: "Operational", sub: "45/100 connections" },
  { name: "Vector Store", detail: "OpenSearch", status: "Operational", sub: "2.4M docs indexed" },
  { name: "Object Storage", detail: "S3", status: "Operational", sub: "847GB used" },
  { name: "LLM Provider", detail: "Bedrock", status: "Operational", sub: "0 throttled" },
  { name: "Email Gateway", detail: "", status: "Operational", sub: "" },
];

const INCIDENTS = [
  { time: "2026-05-19 14:23", user: "M. Chen", action: "API Gateway Restart", severity: "Medium", desc: "High latency on EU region endpoints", duration: "4m 12s", resolved: "Auto-recovery" },
  { time: "2026-05-15 09:41", user: "S. Kapoor", action: "Database Failover", severity: "High", desc: "Primary DB instance became unresponsive", duration: "2m 08s", resolved: "S. Kapoor" },
  { time: "2026-05-12 18:05", user: "J. Ahmed", action: "Cache Clear", severity: "Low", desc: "Stale consent data in Redis cache", duration: "1m 34s", resolved: "J. Ahmed" },
];

const SEVERITY_STYLE: Record<string, string> = { High: "bg-red-100 text-red-600", Medium: "bg-amber-100 text-amber-600", Low: "bg-slate-100 text-slate-600" };

export function SystemHealthPage() {
  const [lastUpdated, setLastUpdated] = useState("2 seconds ago");
  useEffect(() => {
    const t = setInterval(() => setLastUpdated("just now"), 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="p-6">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">System Health</h1>
          <p className="text-sm text-slate-500">Real-time status of VitalAI platform services</p>
        </div>
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <span>Last updated {lastUpdated}</span>
          <button className="text-slate-400 hover:text-slate-600">↻</button>
          <select className="rounded border border-slate-200 px-2 py-1 text-sm">
            <option>Auto-refresh: 5s</option>
          </select>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4 mb-6">
        {[
          { label: "Overall Status", val: "Operational", sub: "All systems running normally", color: "text-emerald-600", dot: "bg-emerald-500" },
          { label: "API Uptime 30d", val: "99.97%", sub: "Last incident 8 days ago", color: "text-slate-900" },
          { label: "Average Latency", val: "248ms", sub: "Last 24 hours", color: "text-slate-900" },
          { label: "Active Sessions", val: "847", sub: "Across 12 tenants", color: "text-slate-900" },
        ].map(t => (
          <div key={t.label} className="rounded-xl border border-t-2 border-brand border-slate-200 bg-white p-5">
            <div className="text-xs text-slate-500 uppercase tracking-wide mb-2">{t.label}</div>
            {t.dot && <div className="flex items-center gap-2 mb-1"><span className={`h-2.5 w-2.5 rounded-full ${t.dot}`}/><span className={`text-2xl font-bold ${t.color}`}>{t.val}</span></div>}
            {!t.dot && <div className={`text-3xl font-bold ${t.color} mb-1`}>{t.val}</div>}
            <div className="text-xs text-slate-500">{t.sub}</div>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white mb-6">
        <h2 className="text-base font-semibold text-slate-900 px-6 py-4 border-b border-slate-100">Agent Status</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              {["Agent Name","Status","Last Heartbeat","Requests 1H","Avg Response","Error Rate","Logs"].map(h => <th key={h} className="px-6 py-3">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {AGENTS.map(a => (
              <tr key={a.name} className="border-t border-slate-100">
                <td className="px-6 py-3 font-medium text-slate-900">{a.name}</td>
                <td className="px-6 py-3"><div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${a.status==="Operational"?"bg-emerald-500":"bg-amber-400"}`}/><span className={a.status==="Degraded"?"text-amber-600 font-medium":"text-slate-700"}>{a.status}</span></div></td>
                <td className="px-6 py-3 text-slate-600">{a.heartbeat}</td>
                <td className="px-6 py-3 text-slate-700">{a.requests}</td>
                <td className="px-6 py-3 text-slate-700">{a.avgResp}</td>
                <td className="px-6 py-3 text-slate-700">{a.errorRate}</td>
                <td className="px-6 py-3"><button className="text-brand hover:underline text-sm">View logs</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid grid-cols-5 gap-4 mb-6">
        {INFRA.map(s => (
          <div key={s.name} className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-xs text-slate-500 mb-1">{s.name}</div>
            <div className="font-semibold text-slate-900 text-sm mb-2">{s.detail || s.name}</div>
            <div className="flex items-center gap-1.5 mb-1"><span className="h-2 w-2 rounded-full bg-emerald-500"/><span className="text-xs text-emerald-600">{s.status}</span></div>
            {s.sub && <div className="text-xs text-slate-500">{s.sub}</div>}
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white">
        <h2 className="text-base font-semibold text-slate-900 px-6 py-4 border-b border-slate-100">Recent Incidents</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              {["Time","User","Action","Severity","Description","Duration","Resolved By"].map(h => <th key={h} className="px-6 py-3">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {INCIDENTS.map(i => (
              <tr key={i.time} className="border-t border-slate-100">
                <td className="px-6 py-3 text-slate-600 font-mono text-xs">{i.time}</td>
                <td className="px-6 py-3 text-slate-700">{i.user}</td>
                <td className="px-6 py-3 text-slate-700">{i.action}</td>
                <td className="px-6 py-3"><span className={`rounded px-2 py-0.5 text-xs font-semibold ${SEVERITY_STYLE[i.severity]}`}>{i.severity}</span></td>
                <td className="px-6 py-3 text-slate-700">{i.desc}</td>
                <td className="px-6 py-3 text-slate-600">{i.duration}</td>
                <td className="px-6 py-3 text-slate-700">{i.resolved}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-center text-xs text-slate-400 py-3 border-t border-slate-100">No incidents in the last 30 days</p>
      </div>
    </div>
  );
}

// Design 14 — Model & Risk Configuration
export function ModelConfigPage() {
  const [temp, setTemp] = useState(0.3);
  const [model, setModel] = useState("Claude Sonnet 4.5");
  const [fallback, setFallback] = useState("Claude Haiku 4.5");
  const [maxTokens, setMaxTokens] = useState("2048");
  const [timeout, setTimeout2] = useState("30");
  const [tab, setTab] = useState("Model Configuration");

  const tabs = ["Model Configuration", "Risk Tier Thresholds", "Agent Prompts"];

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-slate-900">Model and Risk Configuration</h1>
      <p className="text-sm text-slate-500 mb-6">Configure AI models and risk routing thresholds</p>

      <div className="flex gap-6 border-b border-slate-200 mb-6">
        {tabs.map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`pb-3 text-sm font-medium flex items-center gap-2 ${tab === t ? "border-b-2 border-brand text-slate-900" : "text-slate-500 hover:text-slate-700"}`}>
            {t}{t === "Agent Prompts" && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">Coming soon</span>}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-5">
          <div>
            <label className="block text-xs font-bold text-brand uppercase tracking-wide mb-1.5">Primary Model</label>
            <input value={model} onChange={e => setModel(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
            <p className="mt-1 text-xs text-slate-500">Primary model for all agent tasks</p>
          </div>
          <div>
            <label className="block text-xs font-bold text-brand uppercase tracking-wide mb-1.5">Fallback Model</label>
            <input value={fallback} onChange={e => setFallback(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
            <p className="mt-1 text-xs text-slate-500">Used if primary fails or hits rate limits</p>
          </div>
          <div>
            <div className="flex justify-between mb-1.5">
              <label className="text-xs font-bold text-brand uppercase tracking-wide">Temperature</label>
              <span className="text-sm font-semibold text-slate-900">{temp}</span>
            </div>
            <input type="range" min={0} max={1} step={0.1} value={temp} onChange={e => setTemp(Number(e.target.value))}
              className="w-full accent-slate-900" />
            <p className="mt-1 text-xs text-slate-500">Lower values produce more consistent outputs. Recommended 0.2 to 0.4 for clinical workflows</p>
          </div>
          <div>
            <label className="block text-xs font-bold text-brand uppercase tracking-wide mb-1.5">Max Tokens</label>
            <input value={maxTokens} onChange={e => setMaxTokens(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
          </div>
          <div>
            <label className="block text-xs font-bold text-brand uppercase tracking-wide mb-1.5">Timeout</label>
            <div className="flex gap-2 items-center">
              <input value={timeout} onChange={e => setTimeout2(e.target.value)}
                className="flex-1 rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
              <span className="text-sm text-slate-500">seconds</span>
            </div>
          </div>
          <div className="flex gap-3 pt-2">
            <button className="rounded-lg border border-slate-200 px-5 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">Discard</button>
            <button className="rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-hover">Save changes</button>
          </div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="text-base font-semibold text-slate-900 mb-4">Active Configuration</h2>
          <div className="space-y-3 text-sm">
            <div><div className="text-xs text-slate-500">Current model</div><span className="mt-1 inline-block rounded bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">{model}</span></div>
            <div><div className="text-xs text-slate-500">Last changed</div><div className="font-medium text-slate-900">p.desai, 21/05/2026</div></div>
            <div><div className="text-xs text-slate-500">Requests last 24h</div><div className="text-2xl font-bold text-slate-900">1,847</div></div>
          </div>
          <button className="mt-4 w-full rounded-lg border border-slate-200 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50">View change history</button>
        </div>
      </div>
    </div>
  );
}
