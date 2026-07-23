import { useLocation } from "react-router-dom";
import { SearchBar } from "./UI";

// Map route paths to display labels
const routeLabels = {
  "/dashboard": "Dashboard",
  "/patients": "New Patient",
  "/consent": "Consent",
  "/records": "Records",
  "/review-queue": "Triage",
  "/escalations": "Tasks",
  "/inbox": "Inbox",
  "/audit": "Audit",
  "/users": "Users",
  "/settings": "Settings",
};

export default function TopNav() {
  const { pathname } = useLocation();
  const label = routeLabels[pathname] || "VitalAI";

  return (
    <header className="h-10 bg-white border-b border-gray-200 flex items-center px-4 gap-4 shrink-0">
      <span className="text-sm text-gray-500 font-medium w-24 shrink-0">{label}</span>
      <SearchBar placeholder="Search..." />
      <div className="flex items-center gap-1.5 ml-auto">
        <div className="w-5 h-5 border border-gray-400 rounded-sm" />
        <div className="w-5 h-5 border border-gray-400 rounded-sm" />
        <div className="w-7 h-7 rounded-full bg-gray-300" />
      </div>
    </header>
  );
}
