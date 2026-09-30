import type { ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { hasPermission, roleLabel } from "../lib/roles";
import { Avatar } from "../components/ui";
import { MailboxSection } from "./settings/MailboxSection";
import { ManualImportSection } from "./settings/ManualImportSection";
import { OperationsSection } from "./settings/OperationsSection";
import { SettingsSection as SettingsSectionPanel } from "./settings/SettingsSections";

type Section =
  | "General" | "Security" | "Manual import" | "Routing rules" | "Approval tiers"
  | "Integrations" | "Model" | "Operations";

// Everyone gets their own account and password. The clinic settings behind
// GET /settings need configure_governance; Operations needs read_audit.
const CLINIC_SECTIONS: Section[] = ["Routing rules", "Approval tiers", "Integrations", "Model"];
const slug = (s: Section) => s.toLowerCase().replace(/ /g, "-");

function Subsection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-8 last:mb-0">
      <h3 className="mb-3 text-sm font-semibold text-slate-900">{title}</h3>
      {children}
    </section>
  );
}

function AccountCard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  if (!user) return null;
  const initials = user.fullName.split(" ").map(w => w[0]).slice(0, 2).join("").toUpperCase();
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-200 p-4">
      <div className="flex min-w-0 items-center gap-3">
        <Avatar initials={initials} size={40} />
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-900">{user.fullName}</p>
          <p className="truncate text-sm text-slate-500">{user.email}</p>
          <p className="text-xs text-slate-500">{roleLabel(user.role)}</p>
        </div>
      </div>
      <button onClick={() => { logout(); navigate("/login", { replace: true }); }}
        className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
        Log out
      </button>
    </div>
  );
}

function PasswordCard() {
  const navigate = useNavigate();
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-200 p-4">
      <p className="text-sm text-slate-600">Get an email with a link to choose a new password.</p>
      <button onClick={() => navigate("/forgot-password")}
        className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
        Reset password
      </button>
    </div>
  );
}

export function SettingsPage() {
  const { user } = useAuth();
  const has = (p: string) => hasPermission(user, p);
  const canConfigure = has("configure_governance");
  const nav: Section[] = [
    "General", "Security", "Manual import",
    ...(canConfigure ? CLINIC_SECTIONS : []),
    ...(has("read_audit") ? (["Operations"] as Section[]) : []),
  ];
  // The section lives in the URL (?section=integrations), so a link or
  // Microsoft's sign-in redirect can open it directly.
  const [params, setParams] = useSearchParams();
  const active = nav.find(s => slug(s) === params.get("section")) ?? "General";
  const setActive = (s: Section) => setParams({ section: slug(s) });

  return (
    <div className="p-6">
      <h1 className="mb-6 text-2xl font-bold text-slate-900">Settings</h1>
      <div className="flex gap-6">
        <nav className="w-52 shrink-0" aria-label="Settings sections">
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            {nav.map(item => (
              <button key={item} onClick={() => setActive(item)} aria-current={active === item ? "page" : undefined}
                className={`w-full px-4 py-2.5 text-left text-sm transition-colors ${active === item ? "border-l-2 border-brand bg-emerald-50/50 font-semibold text-brand" : "text-slate-700 hover:bg-slate-50"}`}>
                {item}
              </button>
            ))}
          </div>
        </nav>
        <div className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white p-6">
          <h2 className="mb-5 text-base font-semibold text-slate-900">{active}</h2>
          {active === "General" && (
            <>
              <Subsection title="Your account"><AccountCard /></Subsection>
              {canConfigure && <Subsection title="Clinic"><SettingsSectionPanel group="General" /></Subsection>}
            </>
          )}
          {active === "Security" && (
            <>
              <Subsection title="Password"><PasswordCard /></Subsection>
              {canConfigure && <Subsection title="Sign-in"><SettingsSectionPanel group="Security" /></Subsection>}
            </>
          )}
          {active === "Manual import" && <ManualImportSection />}
          {active === "Integrations" && <MailboxSection returned={params.get("mailbox")} />}
          {CLINIC_SECTIONS.includes(active) && active !== "Integrations" && <SettingsSectionPanel group={active} />}
          {active === "Operations" && <OperationsSection />}
        </div>
      </div>
    </div>
  );
}
