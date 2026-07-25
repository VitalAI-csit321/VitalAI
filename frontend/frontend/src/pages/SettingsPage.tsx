import { useState } from "react";
import { useNavigate } from "react-router-dom";

type SettingsSection = "General" | "Security" | "Manual import" | "Routing rules" | "Approval tiers" | "Operational Settings" | "Future state";

const NAV_ITEMS: SettingsSection[] = ["General", "Security", "Manual import", "Routing rules", "Approval tiers", "Operational Settings", "Future state"];

function ManualImportSection() {
  const integrations = [
    { name: "CSV secure file intake", active: true },
    { name: "Administrative upload queue", active: true },
    { name: "EHR integration", active: false },
    { name: "Laboratory systems", active: false },
    { name: "SSO / Identity provider", active: false },
  ];
  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-base font-semibold text-slate-900">Manual data import</h2>
        <button className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50">Integration policy</button>
      </div>
      <div className="space-y-3">
        {integrations.map(int => (
          <div key={int.name} className={`rounded-xl border p-4 ${int.active ? "border-slate-200 bg-white" : "border-dashed border-slate-200 bg-white"}`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className={`h-2.5 w-2.5 rounded-full ${int.active ? "bg-brand" : "bg-slate-300"}`} />
                <span className="font-semibold text-slate-900">{int.name}</span>
              </div>
              {int.active && <button className="rounded-lg bg-brand px-4 py-1.5 text-sm font-semibold text-white hover:bg-brand-hover">Configure</button>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


function RoutingRulesSection() {
  const rules = [
    { id: "R-007", name: "High-risk discharge", tier: "HIGH TIER", tierColor: "bg-red-100 text-red-600", enabled: true, condition: "risk score > 85", action: "Route to Clinical Lead" },
    { id: "R-014", name: "Failed override", tier: "HIGH TIER", tierColor: "bg-red-100 text-red-600", enabled: true, condition: "event = AUTH.DENY", action: "Auto-escalate" },
    { id: "R-021", name: "Consent SLA breach", tier: "MEDIUM TIER", tierColor: "bg-amber-100 text-amber-600", enabled: true, condition: "age > 48h", action: "Notify supervisor" },
    { id: "R-024", name: "Billing threshold", tier: "LOW TIER", tierColor: "bg-slate-100 text-slate-500", enabled: false, condition: "amount < $50", action: "Auto-approve" },
  ];
  const [enabled, setEnabled] = useState(rules.map(r => r.enabled));

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-base font-semibold text-slate-900">Routing rules configuration</h2>
        <div className="flex gap-2">
          <button className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50">Test rule</button>
          <button className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50">Version history</button>
        </div>
      </div>
      <div className="space-y-3">
        {rules.map((r, i) => (
          <div key={r.id} className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-3">
                <span className="font-mono text-sm font-semibold text-slate-700">{r.id}</span>
                <span className="font-semibold text-slate-900">{r.name}</span>
              </div>
              <button className="text-sm font-medium text-brand hover:underline">Edit</button>
            </div>
            <div className="flex items-center gap-3 mb-3">
              <span className={`rounded px-2 py-0.5 text-xs font-bold ${r.tierColor}`}>{r.tier}</span>
              <button onClick={() => setEnabled(e => e.map((v,j) => j===i?!v:v))}
                className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${enabled[i] ? "bg-brand" : "bg-slate-200"}`}>
                <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${enabled[i] ? "translate-x-4" : "translate-x-1"}`} />
              </button>
              <span className="text-xs font-semibold text-slate-600">{enabled[i] ? "ON" : "DISABLED"}</span>
            </div>
            <div className="text-sm text-slate-700">
              <span className="font-semibold text-slate-500">IF </span>{r.condition}
              <br />
              <span className="font-semibold text-slate-500">THEN </span><span className="text-brand font-medium">{r.action}</span>
            </div>
          </div>
        ))}
        <button className="w-full rounded-xl border border-dashed border-slate-200 py-4 text-sm text-slate-500 hover:bg-slate-50">
          + Add new rule
        </button>
      </div>
    </div>
  );
}

function PlaceholderSection({ title }: { title: string }) {
  return <div className="text-sm text-slate-500 py-8 text-center">{title} configuration coming soon.</div>;
}


function OperationalSettingsSection() {
  const navigate = useNavigate();
  return (
    <div>
      <h2 className="text-base font-semibold text-slate-900 mb-5">Operational Settings</h2>
      <div className="rounded-xl border border-slate-200 p-5 flex items-start justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Platform Operations Console</h3>
          <p className="mt-1 text-sm text-slate-500">Access system health monitoring, model configuration, and platform-level operations. Requires operator credentials and MFA.</p>
        </div>
        <button onClick={() => navigate('/platform-ops/login')} className="ml-6 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover whitespace-nowrap">Open Operations</button>
      </div>
    </div>
  );
}

export function SettingsPage() {
  const [active, setActive] = useState<SettingsSection>("Manual import");

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-slate-900 mb-6">Settings and future integrations</h1>
      <div className="flex gap-6">
        <nav className="w-52 shrink-0">
          <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
            {NAV_ITEMS.map(item => (
              <button key={item} onClick={() => setActive(item)}
                className={`w-full text-left px-4 py-2.5 text-sm transition-colors ${active === item ? "text-brand font-semibold border-l-2 border-brand bg-emerald-50/50" : "text-slate-700 hover:bg-slate-50"}`}>
                {item}
              </button>
            ))}
          </div>
        </nav>
        <div className="flex-1 rounded-xl border border-slate-200 bg-white p-6">
          {active === "Manual import" && <ManualImportSection />}
          {active === "Routing rules" && <RoutingRulesSection />}
          {active === "Operational Settings" && <OperationalSettingsSection />}
          {!["Manual import", "Routing rules"].includes(active) && <PlaceholderSection title={active} />}
        </div>
      </div>
    </div>
  );
}
