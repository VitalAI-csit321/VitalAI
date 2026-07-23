import { useState } from "react";
import { PageTitle, Button, Card } from "../components/UI";

const TABS = ["General", "Security", "Manual Import", "Routing Rules", "Approval Tiers", "Notifications", "Future State"];

const integrations = [
  { name: "CSV / Secure File Intake", sub: "Active · MVP", status: "active", action: "Configure" },
  { name: "Administrative Upload Queue", sub: "Active · MVP", status: "active", action: "Configure" },
  { name: "Planned EHR Connection", sub: "Future State", status: "future", action: "Concept" },
  { name: "Planned Lab Connection", sub: "Future State", status: "future", action: "Concept" },
  { name: "Planned SSO Provider", sub: "Future State", status: "future", action: "Concept" },
];

// TODO: Load settings from GET /api/settings
// TODO: Save changes with PATCH /api/settings
export default function Settings() {
  const [activeTab, setActiveTab] = useState("Manual Import");

  return (
    <div>
      <PageTitle title="Settings & Future Integrations" />

      <div className="flex gap-4 bg-white border border-gray-200 rounded overflow-hidden">
        {/* Tabs sidebar */}
        <div className="w-48 border-r border-gray-200 shrink-0 py-3">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`w-full text-left px-4 py-2.5 text-sm transition-colors ${
                activeTab === tab
                  ? "bg-gray-100 font-semibold text-gray-900 border-l-2 border-gray-900"
                  : "text-gray-500 hover:bg-gray-50 border-l-2 border-transparent"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="flex-1 p-5">
          {activeTab === "Manual Import" && <ManualImportTab />}
          {activeTab === "General" && <PlaceholderTab label="General settings" />}
          {activeTab === "Security" && <PlaceholderTab label="Security settings" />}
          {activeTab === "Routing Rules" && <PlaceholderTab label="Routing rules configuration" />}
          {activeTab === "Approval Tiers" && <PlaceholderTab label="Approval tier configuration" />}
          {activeTab === "Notifications" && <PlaceholderTab label="Notification preferences" />}
          {activeTab === "Future State" && <PlaceholderTab label="Future integrations — planned for post-MVP" />}
        </div>
      </div>
    </div>
  );
}

function ManualImportTab() {
  return (
    <div>
      <h3 className="text-sm font-bold text-gray-900 mb-1">Manual Data Import</h3>
      <p className="text-xs text-gray-400 mb-4">MVP supports CSV / secure file intake. Live system connections are future state.</p>

      <div className="flex flex-col gap-2">
        {integrations.map((item) => (
          <div
            key={item.name}
            className={`flex items-center justify-between p-3 rounded border ${
              item.status === "future"
                ? "bg-gray-50 border-dashed border-gray-300 opacity-60"
                : "bg-white border-gray-200"
            }`}
          >
            <div className="flex items-center gap-3">
              <div className={`w-6 h-6 rounded ${item.status === "future" ? "bg-gray-200" : "bg-gray-400"}`} />
              <div>
                <p className={`text-sm font-medium ${item.status === "future" ? "text-gray-400" : "text-gray-800"}`}>
                  {item.name}
                </p>
                <p className="text-xs text-gray-400">{item.sub}</p>
              </div>
            </div>
            <Button variant="secondary" size="sm">{item.action}</Button>
          </div>
        ))}
      </div>
    </div>
  );
}

function PlaceholderTab({ label }) {
  return (
    <div className="flex items-center justify-center h-48 text-sm text-gray-400 border border-dashed border-gray-200 rounded">
      {label}
    </div>
  );
}
