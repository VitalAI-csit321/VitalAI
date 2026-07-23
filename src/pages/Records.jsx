import { useState } from "react";
import { PageTitle, Button, Badge, Select } from "../components/UI";
import { records } from "../data/mockData";

// TODO: Replace with GET /api/records?source=&dateRange=&type=&confidentiality=
export default function Records() {
  const [selected, setSelected] = useState(null);

  return (
    <div>
      <PageTitle title="Record & Information Retrieval" />

      {/* Search bar */}
      <div className="flex gap-2 mb-4">
        <input
          type="search"
          placeholder="Search records..."
          className="flex-1 border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:border-gray-400"
        />
        <Button variant="secondary">Filter</Button>
        <Button variant="primary">Search</Button>
      </div>

      <div className="grid grid-cols-6 gap-4 bg-white border border-gray-200 rounded">
        {/* Filters panel */}
        <div className="col-span-1 border-r border-gray-200 p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Filters</p>
          <div className="flex flex-col gap-4">
            <Select id="source" label="Source" options={["Any", "GP", "Specialist", "Hospital"]} />
            <Select id="date-range" label="Date Range" options={["Any", "Last 7 days", "Last 30 days", "Last 12 months"]} />
            <Select id="doc-type" label="Document Type" options={["Any", "Intake", "Consent", "Insurance", "History", "Referral"]} />
            <Select id="confidentiality" label="Confidentiality" options={["Any", "Standard", "High", "Restricted"]} />
          </div>
        </div>

        {/* Results list */}
        <div className="col-span-3 border-r border-gray-200 p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Results — {records.length} found
          </p>
          <ul className="flex flex-col gap-2">
            {records.map((rec) => (
              <li
                key={rec.id}
                onClick={() => setSelected(rec)}
                className={`flex items-center gap-3 p-2 rounded border cursor-pointer hover:bg-gray-50 ${
                  selected?.id === rec.id ? "border-gray-400 bg-gray-50" : "border-gray-200"
                }`}
              >
                <div className="w-8 h-8 bg-gray-200 rounded shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="h-2.5 bg-gray-300 rounded w-4/5 mb-1.5" />
                  <div className="h-2 bg-gray-200 rounded w-3/5" />
                </div>
                <Badge label="PDF" variant="outline" />
              </li>
            ))}
          </ul>
        </div>

        {/* Preview panel */}
        <div className="col-span-2 p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Preview</p>
          {selected ? (
            <div>
              <p className="text-sm font-semibold text-gray-800 mb-1">{selected.title}</p>
              <p className="text-xs text-gray-400 mb-3">{selected.type} · {selected.date} · {selected.confidentiality}</p>
              {/* TODO: Render PDF preview using a PDF viewer component */}
              <div className="bg-gray-100 border border-dashed border-gray-300 rounded h-64 flex items-center justify-center text-xs text-gray-400">
                Document preview — PDF viewer
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <div className="h-2.5 bg-gray-200 rounded w-full" />
              <div className="h-2 bg-gray-100 rounded w-4/5" />
              <div className="h-2 bg-gray-100 rounded w-3/5" />
              <div className="bg-gray-100 rounded h-48 mt-2" />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
