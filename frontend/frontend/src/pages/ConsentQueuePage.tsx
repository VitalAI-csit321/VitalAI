import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Download } from "lucide-react";
import { listConsentQueue } from "../api/consent";
import type { ConsentQueueRow, ConsentQueueStatus } from "../api/types";
import { Avatar, StatusBadge, Spinner } from "../components/ui";

const STATUS_TONE: Record<ConsentQueueStatus, "green" | "amber" | "red"> = {
  complete: "green",
  pending: "amber",
  review: "red",
};

const STATUS_LABEL: Record<ConsentQueueStatus, string> = {
  complete: "COMPLETE",
  pending: "PENDING",
  review: "REVIEW",
};

const AVATAR_COLORS = ["#0d9488", "#eab308", "#7c3aed", "#db2777", "#0891b2", "#f97316"];

function initials(name: string) {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase();
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function ConsentQueuePage() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<ConsentQueueRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listConsentQueue()
      .then(setRows)
      .catch(() => setError("Could not load the consent queue."))
      .finally(() => setLoading(false));
  }, []);

  const pending = rows.filter((r) => r.status === "pending").length;
  const complete = rows.filter((r) => r.status === "complete").length;
  const review = rows.filter((r) => r.status === "review").length;

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Consent queue</h1>
          <p className="mt-1 text-sm text-slate-500">
            {rows.length} records • {pending} awaiting
          </p>
        </div>
        <div className="flex gap-3">
          <button className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
            <Download className="h-4 w-4" />
            Export
          </button>
          <button
            onClick={() => navigate("/consent/capture")}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover"
          >
            New consent
          </button>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-200 border-l-4 border-l-amber-400 bg-white p-5">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Pending</div>
          <div className="mt-2 text-3xl font-bold text-slate-900">{pending}</div>
        </div>
        <div className="rounded-xl border border-slate-200 border-l-4 border-l-brand bg-white p-5">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Completed</div>
          <div className="mt-2 text-3xl font-bold text-slate-900">{complete}</div>
        </div>
        <div className="rounded-xl border border-slate-200 border-l-4 border-l-red-400 bg-white p-5">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Requires review
          </div>
          <div className="mt-2 text-3xl font-bold text-slate-900">{review}</div>
        </div>
      </div>

      <div className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <th className="px-6 py-3">Patient</th>
              <th className="px-6 py-3">Form</th>
              <th className="px-6 py-3">Submitted</th>
              <th className="px-6 py-3">Status</th>
              <th className="px-6 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className="px-6 py-8">
                  <Spinner />
                </td>
              </tr>
            ) : error ? (
              <tr>
                <td colSpan={5} className="px-6 py-8 text-sm text-red-600">
                  {error}
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-8 text-sm text-slate-500">
                  No consent records yet.
                </td>
              </tr>
            ) : (
              rows.map((r, i) => (
                <tr key={r.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <Avatar
                        initials={initials(r.patientName)}
                        color={AVATAR_COLORS[i % AVATAR_COLORS.length]}
                        size={32}
                      />
                      <span className="font-medium text-slate-900">{r.patientName}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-slate-700">{r.form}</td>
                  <td className="px-6 py-4 text-slate-600">{fmtDate(r.submitted)}</td>
                  <td className="px-6 py-4">
                    <StatusBadge tone={STATUS_TONE[r.status]}>{STATUS_LABEL[r.status]}</StatusBadge>
                  </td>
                  <td className="px-6 py-4">
                    <button
                      onClick={() => navigate(`/cases/${r.caseId}`)}
                      className="font-medium text-brand hover:underline"
                    >
                      View
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
