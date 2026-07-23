import { NavLink } from "react-router-dom";

const navGroups = [
  {
    label: "WORKSPACE",
    items: [
      { to: "/dashboard", label: "Dashboard" },
      { to: "/patients", label: "Patients" },
      { to: "/consent", label: "Consent" },
      { to: "/records", label: "Records" },
      { to: "/review-queue", label: "Review Queue" },
      { to: "/escalations", label: "Escalations" },
      { to: "/inbox", label: "Inbox" },
    ],
  },
  {
    label: "ADMIN",
    items: [
      { to: "/audit", label: "Audit" },
      { to: "/users", label: "Users" },
      { to: "/settings", label: "Settings" },
    ],
  },
];

export default function Sidebar() {
  return (
    <aside className="w-52 min-h-screen bg-white border-r border-gray-200 flex flex-col shrink-0">
      {/* Logo */}
      <div className="flex items-center gap-2 px-4 py-4 border-b border-gray-200">
        <div className="w-7 h-7 bg-gray-200 rounded-lg" />
        <span className="font-bold text-gray-900 text-base">VitalAI</span>
      </div>

      {/* Nav groups */}
      <nav className="flex-1 py-4 px-2 overflow-y-auto">
        {navGroups.map((group) => (
          <div key={group.label} className="mb-4">
            <p className="text-xs text-gray-400 font-semibold tracking-widest px-2 mb-1">{group.label}</p>
            {group.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `flex items-center gap-2 px-2 py-1.5 rounded text-sm mb-0.5 transition-colors ${
                    isActive
                      ? "bg-gray-100 text-gray-900 font-semibold border-l-2 border-gray-900"
                      : "text-gray-600 hover:bg-gray-50 border-l-2 border-transparent"
                  }`
                }
              >
                {/* Checkbox-style icon matching wireframe */}
                <span className="w-4 h-4 border border-gray-400 rounded-sm inline-block shrink-0" />
                {item.label}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
    </aside>
  );
}
