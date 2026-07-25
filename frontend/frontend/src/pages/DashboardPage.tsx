import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import { getDashboard } from "../api/misc";
import { useAuth } from "../lib/auth";
import type { DashboardSummary } from "../api/types";
import { Spinner } from "../components/ui";

const TILE_BORDER = ["border-t-brand", "border-t-amber-400", "border-t-red-400", "border-t-brand"];

function Tile({ label, value, borderClass }: { label: string; value: number; borderClass: string }) {
  return (
    <div className={`rounded-xl border border-slate-200 border-t-2 ${borderClass} bg-white p-5`}>
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-3xl font-bold text-slate-900">{value}</div>
    </div>
  );
}

export function DashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDashboard()
      .then(setData)
      .catch(() => setError("Could not load dashboard data."));
  }, []);

  const title = user ? `Mr ${user.fullName}` : "";

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Overview</h1>
          <p className="mt-1 text-sm text-slate-500">Welcome back, {title}</p>
        </div>
        <button
          onClick={() => navigate("/patients/onboarding")}
          className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover"
        >
          New case
        </button>
      </div>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      {!data && !error ? (
        <div className="mt-8">
          <Spinner />
        </div>
      ) : data ? (
        <>
          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Tile label="Open cases" value={data.openCases} borderClass={TILE_BORDER[0]} />
            <Tile
              label="Awaiting approval"
              value={data.awaitingApproval}
              borderClass={TILE_BORDER[1]}
            />
            <Tile label="Escalations" value={data.escalations} borderClass={TILE_BORDER[2]} />
            <Tile label="Audit events" value={data.auditEvents} borderClass={TILE_BORDER[3]} />
          </div>

          <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <h2 className="text-base font-semibold text-slate-900">Workflow Status</h2>
              <div className="mt-4 h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data.workflowByDay} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
                    <CartesianGrid strokeDasharray="4 4" stroke="#e2e8f0" vertical={false} />
                    <XAxis
                      dataKey="day"
                      tickLine={false}
                      axisLine={false}
                      tick={{ fill: "#64748b", fontSize: 12 }}
                    />
                    <YAxis
                      tickLine={false}
                      axisLine={false}
                      tick={{ fill: "#64748b", fontSize: 12 }}
                      ticks={[0, 9, 18, 27, 36]}
                      domain={[0, 36]}
                    />
                    <Bar dataKey="value" fill="#0d9488" radius={[3, 3, 0, 0]} barSize={44} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <h2 className="text-base font-semibold text-slate-900">Pending Reviews</h2>
              <div className="mt-4 space-y-2">
                {data.pendingReviews.map((r) => (
                  <div
                    key={r.id}
                    className="flex items-center justify-between rounded-lg bg-slate-50 px-4 py-3"
                  >
                    <div>
                      <div className="text-sm font-semibold text-slate-900">{r.name}</div>
                      <div className="text-xs text-slate-500">{r.kind}</div>
                    </div>
                    {r.isNew && (
                      <span className="rounded bg-brand px-2 py-0.5 text-xs font-semibold text-white">
                        NEW
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
