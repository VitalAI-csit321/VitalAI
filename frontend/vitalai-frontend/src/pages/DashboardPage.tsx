import { useAuthStore } from "../store/authStore";
import { Card, Topbar, C } from "../components/ui";
import { ROLES } from "../types";

export function DashboardPage() {
  const { user } = useAuthStore();
  const role = user?.role;

  const roleLabel: Record<string, string> = {
    front_desk:  "Front Desk",
    ops_manager: "Ops Manager",
    admin:       "Admin",
  };

  // What this role can access
  const access = [
    { label: "Patient Intake",  path: "/intake",  allowed: true,                                                        desc: "Register a new patient case" },
    { label: "Consent",         path: "/consent", allowed: true,                                                        desc: "Create and capture consent records" },
    { label: "Triage",          path: "/triage",  allowed: role === ROLES.OPS_MANAGER || role === ROLES.ADMIN,          desc: "Run AI triage on a case" },
    { label: "Audit Log",       path: "/audit",   allowed: role === ROLES.ADMIN,                                        desc: "View audit events for a case" },
  ];

  return (
    <div>
      <Topbar />
      <div style={{ padding: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: C.text, margin: "0 0 4px" }}>Overview</h1>
        <p style={{ fontSize: 13, color: C.textMid, margin: "0 0 24px" }}>Welcome back, {user?.full_name ?? "—"} · {roleLabel[role ?? ""] ?? role}</p>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 14, maxWidth: 680 }}>
          {access.map(item => (
            <Card key={item.path} style={{ opacity: item.allowed ? 1 : 0.45, borderTop: `3px solid ${item.allowed ? C.teal : C.border}` }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: C.text, marginBottom: 4 }}>{item.label}</div>
              <div style={{ fontSize: 12, color: C.textMid, marginBottom: 12 }}>{item.desc}</div>
              {item.allowed
                ? <a href={item.path} style={{ color: C.teal, fontSize: 13, fontWeight: 600, textDecoration: "none" }}>Open →</a>
                : <span style={{ fontSize: 12, color: C.textMuted }}>Not available for your role</span>}
            </Card>
          ))}
        </div>

        <div style={{ marginTop: 24, padding: 14, background: C.tealLight, borderRadius: 8, maxWidth: 680 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.teal, marginBottom: 4 }}>Sprint 2 — FE-SHELL + FE-WIRE</div>
          <div style={{ fontSize: 12, color: C.teal }}>Frontend wired to Sprint 1 backend at <code style={{ fontFamily: "monospace" }}>localhost:8000/api/v1</code></div>
        </div>
      </div>
    </div>
  );
}
