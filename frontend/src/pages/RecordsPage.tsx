import { useState } from "react";
import { Search } from "lucide-react";
import { placeholderRecords } from "../api/misc";
import type { RecordDocument } from "../api/types";

export function RecordsPage() {
  const [selected, setSelected] = useState<RecordDocument>(placeholderRecords[0]);
  const records = placeholderRecords;

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-slate-900">Record and information retrieval</h1>

      <div className="mt-6 flex gap-3">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            placeholder="Search by patient name, MRN, or document type..."
            className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm outline-none focus:border-brand"
          />
        </div>
        <button className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50">
          Filters
        </button>
        <button className="rounded-lg bg-brand px-5 py-2.5 text-sm font-semibold text-white hover:bg-brand-hover">
          Search
        </button>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1fr_1.3fr_1.3fr]">
        {/* Filters */}
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="text-base font-semibold text-slate-900">Filters</h2>

          <div className="mt-5 space-y-5 text-sm">
            <div>
              <div className="mb-2 font-medium text-slate-700">Source</div>
              <div className="flex flex-wrap gap-2">
                <span className="rounded bg-slate-100 px-2.5 py-1 text-xs text-slate-600">
                  Emergency Dept
                </span>
                <span className="rounded bg-slate-100 px-2.5 py-1 text-xs text-slate-600">
                  Pathology
                </span>
              </div>
            </div>
            <div>
              <div className="mb-2 font-medium text-slate-700">Date range</div>
              <span className="rounded bg-slate-100 px-2.5 py-1 text-xs text-slate-600">
                Last 7 days
              </span>
            </div>
            <div>
              <div className="mb-2 font-medium text-slate-700">Type</div>
              <span className="rounded bg-slate-100 px-2.5 py-1 text-xs text-slate-600">
                Clinical note
              </span>
            </div>
            <div>
              <div className="mb-2 font-medium text-slate-700">Confidentiality</div>
              <span className="rounded bg-emerald-100 px-2.5 py-1 text-xs text-emerald-700">
                Standard
              </span>
            </div>
          </div>
        </div>

        {/* Results */}
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="text-sm text-slate-500">{records.length} documents found</div>
          <div className="mt-4 space-y-3">
            {records.map((doc) => {
              const active = doc.id === selected.id;
              return (
                <button
                  key={doc.id}
                  onClick={() => setSelected(doc)}
                  className={`w-full rounded-lg border p-4 text-left transition-colors ${
                    active
                      ? "border-brand bg-emerald-50/50"
                      : "border-transparent hover:bg-slate-50"
                  }`}
                >
                  <div className="text-sm font-semibold text-slate-900">{doc.title}</div>
                  <div className="mt-0.5 text-xs text-slate-500">
                    {doc.type} • {doc.date}
                  </div>
                  <div className="text-xs text-slate-400">{doc.source}</div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Detail */}
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="text-base font-semibold text-slate-900">{selected.title}</h2>
          <div className="mt-4 grid grid-cols-2 gap-y-3 text-sm">
            <div>
              <span className="text-slate-500">Type: </span>
              <span className="font-medium text-slate-800">{selected.type}</span>
            </div>
            <div>
              <span className="text-slate-500">Date: </span>
              <span className="font-medium text-slate-800">{selected.date}</span>
            </div>
            <div>
              <span className="text-slate-500">Source: </span>
              <span className="font-medium text-slate-800">{selected.source}</span>
            </div>
            <div>
              <span className="text-slate-500">Pages: </span>
              <span className="font-medium text-slate-800">{selected.pages}</span>
            </div>
          </div>
          <button className="mt-5 w-full rounded-lg bg-brand py-2.5 text-sm font-semibold text-white hover:bg-brand-hover">
            Open full record
          </button>
        </div>
      </div>
    </div>
  );
}
