import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { getDashboard } from "../api/misc";
import { useAuth } from "../lib/auth";
import type { DashboardSummary } from "../api/types";
import { Spinner } from "../components/ui";

export function DashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState<DashboardSummary | null>(null);

  useEffect(() => { getDashboard().then(setData).catch(() => {}); }, []);

  const tiles = [
    { label: "Open cases", key: "openCases", color: "border-t-brand", path: "/patients" },
    { label: "Awaiting approval", key: "awaitingApproval", color: "border-t-amber-400", path: "/review-queue" },
    { label: "Escalations", key: "escalations", color: "border-t-red-400", path: "/escalations" },
    { label: "Audit events", key: "auditEvents", color: "border-t-brand", path: "/audit" },
  ] as const;

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Overview</h1>
          <p className="mt-1 text-sm text-slate-500">Welcome back, {user?.fullName ?? ""}</p>
        </div>
        <button onClick={() => navigate("/patients/onboarding")} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover">New case</button>
      </div>

      {!data ? <div className="mt-8"><Spinner /></div> : <>
        <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          {tiles.map(t => (
            <div key={t.key} onClick={() => navigate(t.path)} className={`cursor-pointer rounded-xl border border-slate-200 border-t-2 ${t.color} bg-white p-5 hover:shadow-md transition-shadow`}>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{t.label}</div>
              <div className="mt-2 text-3xl font-bold text-slate-900">{data[t.key]}</div>
            </div>
          ))}
        </div>

        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-base font-semibold text-slate-900">Workflow Status</h2>
            <div className="mt-4 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.workflowByDay} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
                  <CartesianGrid strokeDasharray="4 4" stroke="#e2e8f0" vertical={false} />
                  <XAxis dataKey="day" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 12 }} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 12 }} />
                  <Bar dataKey="value" fill="#0d9488" radius={[3,3,0,0]} barSize={40} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-base font-semibold text-slate-900">Pending Reviews</h2>
            <div className="mt-4 space-y-2">
              {data.pendingReviews.map(r => (
                <button key={r.id} onClick={() => navigate("/review-queue")}
                  className="flex w-full items-center justify-between rounded-lg bg-slate-50 px-4 py-3 hover:bg-slate-100 text-left">
                  <div><div className="text-sm font-semibold text-slate-900">{r.name}</div><div className="text-xs text-slate-500">{r.kind}</div></div>
                  {r.isNew && <span className="rounded bg-brand px-2 py-0.5 text-xs font-semibold text-white">NEW</span>}
                </button>
              ))}
            </div>
          </div>
        </div>
      </>}
    </div>
  );
}
