import { PageTitle } from "../components/UI";
import { escalationColumns } from "../data/mockData";

const priorityDot = {
  High: "bg-gray-900",
  Medium: "bg-gray-400",
  Low: "bg-transparent border border-gray-400",
};

// TODO: Replace with GET /api/escalations
// TODO: Add drag-and-drop between columns when needed
export default function Escalations() {
  return (
    <div>
      <PageTitle title="Escalation Routing" />

      <div className="grid grid-cols-4 gap-4">
        {escalationColumns.map((col) => (
          <div key={col.id} className="bg-white border border-gray-200 rounded p-3 flex flex-col gap-3">
            <h3 className="text-sm font-semibold text-gray-700">
              {col.label} · <span className="font-normal text-gray-400">{col.count}</span>
            </h3>

            {col.items.map((item) => (
              <div key={item.id} className="bg-gray-50 border border-gray-200 rounded p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono text-xs text-gray-700">{item.id}</span>
                  <span className={`w-2.5 h-2.5 rounded-full ${priorityDot[item.priority]}`} />
                </div>

                {/* Placeholder description lines */}
                <div className="h-2 bg-gray-200 rounded w-full mb-1.5" />
                <div className="h-2 bg-gray-200 rounded w-3/5 mb-3" />

                <div className="flex items-center justify-between">
                  <div className="w-5 h-5 rounded-full bg-gray-300" />
                  <span className="text-xs text-gray-400">{item.date}</span>
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
