import { NavLink } from "react-router-dom";
import {
  LayoutGrid,
  Users as UsersIcon,
  FileText,
  FolderClosed,
  Mail,
  ClipboardList,
  AlertTriangle,
  ShieldCheck,
  UserCog,
  Settings,
} from "lucide-react";
import { useAuth } from "../lib/auth";
import { Avatar } from "./ui";

// Order and labels match the sponsor-approved sidebar exactly.
const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutGrid },
  { to: "/patients", label: "Patients", icon: UsersIcon },
  { to: "/consent", label: "Consent", icon: FileText },
  { to: "/records", label: "Records", icon: FolderClosed },
  { to: "/inbox", label: "Inbox", icon: Mail },
  { to: "/review-queue", label: "Review Queue", icon: ClipboardList },
  { to: "/escalations", label: "Escalations", icon: AlertTriangle },
  { to: "/audit", label: "Audit", icon: ShieldCheck },
  { to: "/users", label: "Users", icon: UserCog },
  { to: "/settings", label: "Settings", icon: Settings },
];

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function roleLabel(role: string): string {
  return role
    .split("_")
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

export function Sidebar() {
  const { user } = useAuth();
  const name = user?.fullName ?? "";

  return (
    <aside className="flex h-full w-56 shrink-0 flex-col bg-sidebar text-slate-200">
      <div className="px-6 py-5 text-lg font-bold text-white">VitalAI</div>

      <nav className="flex-1 space-y-1 px-3">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-sidebar-active text-white"
                  : "text-slate-300 hover:bg-sidebar-hover hover:text-white"
              }`
            }
          >
            <Icon className="h-[18px] w-[18px]" strokeWidth={1.75} />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="flex items-center gap-3 border-t border-white/10 px-4 py-4">
        <Avatar initials={name ? initialsOf(name) : "–"} size={36} />
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-white">{name || "—"}</div>
          <div className="text-xs text-slate-400">{user ? roleLabel(user.role) : ""}</div>
        </div>
      </div>
    </aside>
  );
}
