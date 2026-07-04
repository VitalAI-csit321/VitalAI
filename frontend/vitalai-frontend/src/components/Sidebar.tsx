import { NavLink, useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/authStore";
import { C } from "./ui";
import { ROLES, type UserRole } from "../types";

interface NavItem {
  to: string;
  icon: string;
  label: string;
  roles?: UserRole[];  // undefined = any authenticated user
}

// Matches the actual backend role set: front_desk, ops_manager, admin
const NAV: NavItem[] = [
  { to: "/dashboard",  icon: "⊞",  label: "Dashboard" },
  { to: "/intake",     icon: "📋", label: "Intake",       roles: [ROLES.FRONT_DESK, ROLES.OPS_MANAGER, ROLES.ADMIN] },
  { to: "/consent",    icon: "📄", label: "Consent",      roles: [ROLES.FRONT_DESK, ROLES.OPS_MANAGER, ROLES.ADMIN] },
  { to: "/triage",     icon: "🚑", label: "Triage",       roles: [ROLES.OPS_MANAGER, ROLES.ADMIN] },
  { to: "/audit",      icon: "📋", label: "Audit",        roles: [ROLES.ADMIN] },
];

export function Sidebar() {
  const { user, clearAuth } = useAuthStore();
  const navigate = useNavigate();

  const initials = user?.full_name
    ? user.full_name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase()
    : "??";

  const visible = NAV.filter(item => !item.roles || (user && item.roles.includes(user.role)));

  return (
    <div style={{ width: 188, background: C.sidebar, display: "flex", flexDirection: "column", height: "100vh", position: "fixed", top: 0, left: 0, zIndex: 50 }}>
      <div style={{ padding: "20px 18px 12px", fontSize: 18, fontWeight: 800, color: "#fff" }}>VitalAI</div>
      <nav style={{ flex: 1, padding: "0 8px", overflowY: "auto" }}>
        {visible.map(item => (
          <NavLink key={item.to} to={item.to} style={({ isActive }) => ({
            display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", borderRadius: 7,
            marginBottom: 1, fontSize: 13, fontWeight: 500, textDecoration: "none",
            background: isActive ? "rgba(43,169,155,0.18)" : "transparent",
            color: isActive ? C.teal : "#9BA5B7", transition: "all .12s",
          })}>
            <span style={{ fontSize: 14 }}>{item.icon}</span>{item.label}
          </NavLink>
        ))}
      </nav>
      <div style={{ padding: "12px 14px", borderTop: "1px solid rgba(255,255,255,0.06)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
          <div style={{ width: 30, height: 30, borderRadius: "50%", background: C.teal, color: "#fff", fontWeight: 700, fontSize: 11, display: "flex", alignItems: "center", justifyContent: "center" }}>{initials}</div>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: "#E2E8F0" }}>{user?.full_name ?? "—"}</div>
            <div style={{ fontSize: 10, color: "#9BA5B7", textTransform: "capitalize" }}>{user?.role?.replace("_", " ")}</div>
          </div>
        </div>
        <button onClick={() => { clearAuth(); navigate("/login"); }}
          style={{ width: "100%", padding: "5px 0", background: "rgba(255,255,255,0.06)", border: "none", borderRadius: 5, color: "#9BA5B7", fontSize: 12, cursor: "pointer" }}>
          Sign out
        </button>
      </div>
    </div>
  );
}
