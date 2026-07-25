import { useEffect, useState } from "react";
import { UserPlus } from "lucide-react";
import { listUsers } from "../api/auth";
import type { ManagedUser } from "../api/types";
import { Avatar } from "../components/ui";

const ROLE_STYLE: Record<string, string> = {
  doctor: "border border-brand text-brand",
  operator: "bg-slate-100 text-slate-700",
  admin: "bg-slate-800 text-white",
  front_desk: "bg-slate-100 text-slate-600",
};

const ROLE_LABEL: Record<string, string> = {
  doctor: "CLINICIAN", operator: "OPERATOR", admin: "ADMIN", front_desk: "FRONT DESK",
};

const PERMISSIONS_LABEL: Record<string, string> = {
  admin: "Full Access", operator: "Full Access", doctor: "Limited", front_desk: "Standard",
};

const AVATAR_COLORS = ["#0d9488","#7c3aed","#0d9488","#eab308","#f97316","#db2777","#64748b"];

// Placeholder users matching design 8
const PLACEHOLDER_USERS: ManagedUser[] = [
  { id:"1", email:"s.kapoor@royalmelb.health", fullName:"Dr Sanjay Kapoor", role:"doctor", department:"Emergency", isActive:true, grantedPermissions:[], createdAt:"2026-01-01T00:00:00Z", lastActive:"Active now" },
  { id:"2", email:"c.hines@royalmelb.health", fullName:"Dr Catherine Hines", role:"doctor", department:"Emergency", isActive:true, grantedPermissions:[], createdAt:"2026-01-01T00:00:00Z", lastActive:"5 mins ago" },
  { id:"3", email:"m.alvarez@royalmelb.health", fullName:"Maria Alvarez", role:"operator", department:"Admin", isActive:true, grantedPermissions:[], createdAt:"2026-01-01T00:00:00Z", lastActive:"1 hour ago" },
  { id:"4", email:"l.kim@royalmelb.health", fullName:"Dr Lisa Kim", role:"operator", department:"Admin", isActive:true, grantedPermissions:[], createdAt:"2026-01-01T00:00:00Z", lastActive:"2 hours ago" },
  { id:"5", email:"m.brooks@royalmelb.health", fullName:"Mark Brooks", role:"operator", department:"Records", isActive:false, grantedPermissions:[], createdAt:"2026-01-01T00:00:00Z", lastActive:"Yesterday" },
  { id:"6", email:"j.taylor@royalmelb.health", fullName:"Dr James Taylor", role:"front_desk", department:"Front Office", isActive:true, grantedPermissions:[], createdAt:"2026-01-01T00:00:00Z", lastActive:"2 days ago" },
  { id:"7", email:"s.chen@royalmelb.health", fullName:"Sophie Chen", role:"admin", department:"Legal", isActive:true, grantedPermissions:[], createdAt:"2026-01-01T00:00:00Z", lastActive:"3 days ago" },
];

function InviteModal({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({ fullName: "Dr Liang Lim", email: "", role: "Clinician", department: "Cardiology", mfa: true });
  const chips = ["VIEW CASES", "APPROVE HITL", "READ RECORDS", "CAPTURE CONSENT", "SEND MESSAGES", "READ AUDIT"];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-bold text-slate-900">Invite new user</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xl">×</button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1.5">Full name</label>
            <input value={form.fullName} onChange={e => setForm(f => ({...f, fullName: e.target.value}))}
              className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1.5">Email address</label>
            <input value={form.email} onChange={e => setForm(f => ({...f, email: e.target.value}))}
              placeholder="email@royalmelb.health"
              className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1.5">Role</label>
              <input value={form.role} onChange={e => setForm(f => ({...f, role: e.target.value}))}
                className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
            </div>
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1.5">Department</label>
              <input value={form.department} onChange={e => setForm(f => ({...f, department: e.target.value}))}
                className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
            </div>
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-2">Permissions</label>
            <div className="flex flex-wrap gap-2">
              {chips.map(c => <span key={c} className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600">{c}</span>)}
            </div>
          </div>
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-start gap-2">
                <span className="text-amber-500">⚠</span>
                <div>
                  <p className="text-sm font-semibold text-amber-800">MFA required</p>
                  <p className="text-sm text-amber-700">Multi-factor authentication will be enforced for this user</p>
                </div>
              </div>
              <button onClick={() => setForm(f => ({...f, mfa: !f.mfa}))}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${form.mfa ? "bg-brand" : "bg-slate-200"}`}>
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${form.mfa ? "translate-x-6" : "translate-x-1"}`} />
              </button>
            </div>
          </div>
        </div>

        <div className="mt-5 flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-lg border border-slate-200 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
          <button onClick={onClose} className="flex-1 rounded-lg bg-brand py-2.5 text-sm font-semibold text-white hover:bg-brand-hover">Send invite</button>
        </div>
      </div>
    </div>
  );
}

export function UsersPage() {
  const [users, setUsers] = useState<ManagedUser[]>(PLACEHOLDER_USERS);
  const [search, setSearch] = useState("");
  const [showInvite, setShowInvite] = useState(false);

  useEffect(() => {
    listUsers({ limit: 20 })
      .then(res => { if (res.items.length > 0) setUsers(res.items); })
      .catch(() => {});
  }, []);

  const active = users.filter(u => u.isActive).length;
  const pending = users.filter(u => !u.isActive).length;
  const filtered = users.filter(u => !search || u.fullName.toLowerCase().includes(search.toLowerCase()) || u.email.includes(search));

  function toggleActive(id: string) {
    setUsers(u => u.map(user => user.id === id ? { ...user, isActive: !user.isActive } : user));
  }

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">User management • RBAC</h1>
          <p className="mt-1 text-sm text-slate-500">
            {active} active • {pending} pending
            <span className="ml-2 text-brand font-medium">MFA enforced</span>
          </p>
        </div>
        <button onClick={() => setShowInvite(true)} className="flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover">
          <UserPlus className="h-4 w-4" />Invite user
        </button>
      </div>

      <div className="mt-6 flex gap-3">
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search users..."
          className="flex-1 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm outline-none focus:border-brand" />
        {["All roles", "All departments", "Active", "Export"].map((label, i) => (
          <button key={label} className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50 whitespace-nowrap">
            {i === 3 ? <span className="flex items-center gap-1"><Download />Export</span> : label}
          </button>
        ))}
      </div>

      <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              {["User", "Role", "Department", "Permissions", "Last Active", "Status"].map(h => (
                <th key={h} className="px-6 py-3">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((u, i) => (
              <tr key={u.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                <td className="px-6 py-4">
                  <div className="flex items-center gap-3">
                    <Avatar initials={(u.fullName[0]+(u.fullName.split(" ").pop()?.[0]??u.fullName[1]??"")||"?").toUpperCase()} color={AVATAR_COLORS[i % AVATAR_COLORS.length]} size={36} />
                    <div>
                      <div className="font-semibold text-slate-900">{u.fullName}</div>
                      <div className="text-xs text-slate-500">{u.email}</div>
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4">
                  <span className={`rounded px-2.5 py-0.5 text-xs font-bold ${ROLE_STYLE[u.role] ?? "bg-slate-100 text-slate-600"}`}>{ROLE_LABEL[u.role] ?? u.role.toUpperCase()}</span>
                </td>
                <td className="px-6 py-4 text-slate-700">{u.department ?? "—"}</td>
                <td className="px-6 py-4 text-slate-700">{PERMISSIONS_LABEL[u.role] ?? "Standard"}</td>
                <td className="px-6 py-4 text-slate-600">{u.lastActive ?? "—"}</td>
                <td className="px-6 py-4">
                  <button onClick={() => toggleActive(u.id)}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${u.isActive ? "bg-brand" : "bg-slate-200"}`}>
                    <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${u.isActive ? "translate-x-6" : "translate-x-1"}`} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showInvite && <InviteModal onClose={() => setShowInvite(false)} />}
    </div>
  );
}

// Inline Download to avoid extra import
function Download() { return <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>; }
