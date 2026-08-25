import { useState } from "react";
import { useNavigate } from "react-router-dom";

type SettingsSection = "General" | "Security" | "Manual import" | "Routing rules" | "Approval tiers" | "Operational Settings" | "Future state";

const NAV_ITEMS: SettingsSection[] = ["General", "Security", "Manual import", "Routing rules", "Approval tiers", "Operational Settings", "Future state"];

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
          {active === "Operational Settings" && <OperationalSettingsSection />}
          {!["Operational Settings"].includes(active) && <PlaceholderSection title={active} />}
        </div>
      </div>
    </div>
  );
}
