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

  const access = [
    { label: "Patient Intake",  path: "/intake",  icon: "📋", allowed: true,                                               desc: "Register a new patient case and capture their contact reason" },
    { label: "Consent",         path: "/consent", icon: "📄", allowed: true,                                               desc: "Create, capture and manage patient consent records" },
    { label: "Triage",          path: "/triage",  icon: "🚑", allowed: role === ROLES.OPS_MANAGER || role === ROLES.ADMIN, desc: "Run AI triage on a case and get urgency classification" },
    { label: "Audit Log",       path: "/audit",   icon: "📋", allowed: role === ROLES.ADMIN,                               desc: "View all audit events for a case — admin only" },
  ];

  return (
    <div style={{ minHeight: "100vh", background: C.surfaceDim }}>
      <Topbar />
      <div style={{ maxWidth: 900, margin: "0 auto", padding: "40px 24px" }}>

        {/* Welcome header */}
        <div style={{ marginBottom: 32 }}>
          <h1 style={{ fontSize: 24, fontWeight: 800, color: C.text, margin: "0 0 6px" }}>
            Welcome back, {user?.full_name ?? "—"} 👋
          </h1>
          <p style={{ fontSize: 14, color: C.textMid, margin: 0 }}>
            {roleLabel[role ?? ""] ?? role} · VitalAI Sprint 2
          </p>
        </div>

        {/* Stats row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 32 }}>
          {[
            { label: "Your role",    value: roleLabel[role ?? ""] ?? role ?? "—", accent: C.teal  },
            { label: "Sprint",       value: "2 of 4",                              accent: C.amber },
            { label: "System",       value: "Online",                              accent: C.green },
          ].map(s => (
            <div key={s.label} style={{
              background: "#fff", borderRadius: 10, padding: "18px 20px",
              borderTop: `3px solid ${s.accent}`,
              border: `1px solid ${C.border}`,
            }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>{s.label}</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: C.text }}>{s.value}</div>
            </div>
          ))}
        </div>

        {/* Navigation cards */}
        <h2 style={{ fontSize: 15, fontWeight: 700, color: C.text, marginBottom: 16 }}>Quick access</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 16, marginBottom: 32 }}>
          {access.map(item => (
            <div key={item.path}
              onClick={() => item.allowed && (window.location.href = item.path)}
              style={{
                background: "#fff", borderRadius: 10, padding: "20px 24px",
                border: `1px solid ${C.border}`,
                borderLeft: `4px solid ${item.allowed ? C.teal : C.border}`,
                opacity: item.allowed ? 1 : 0.45,
                cursor: item.allowed ? "pointer" : "default",
                transition: "box-shadow .15s",
              }}
              onMouseEnter={e => { if (item.allowed) (e.currentTarget as HTMLDivElement).style.boxShadow = "0 4px 12px rgba(0,0,0,0.08)"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.boxShadow = "none"; }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                <span style={{ fontSize: 20 }}>{item.icon}</span>
                <span style={{ fontSize: 15, fontWeight: 700, color: item.allowed ? C.text : C.textMuted }}>{item.label}</span>
              </div>
              <p style={{ fontSize: 13, color: C.textMid, margin: "0 0 12px", lineHeight: 1.5 }}>{item.desc}</p>
              {item.allowed
                ? <span style={{ fontSize: 13, color: C.teal, fontWeight: 600 }}>Open →</span>
                : <span style={{ fontSize: 12, color: C.textMuted }}>Not available for your role</span>}
            </div>
          ))}
        </div>

        {/* Info banner */}
        <div style={{ background: C.tealLight, border: `1px solid ${C.teal}30`, borderRadius: 10, padding: "16px 20px", display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 20 }}>ℹ️</span>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: C.teal, marginBottom: 2 }}>Sprint 2 — Frontend wired to backend</div>
            <div style={{ fontSize: 12, color: C.teal }}>Connected to <code style={{ fontFamily: "monospace" }}>localhost:8000/api/v1</code> · RAG query screen activates once Amin deploys FR-RAG-01</div>
          </div>
        </div>

      </div>
    </div>
  );
}