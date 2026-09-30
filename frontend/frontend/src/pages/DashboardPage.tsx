import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getDashboard } from "../api/misc";
import { createEpisode } from "../api/episodes";
import { describeApiError } from "../lib/apiClient";
import { DoctorSelect, PatientSearch } from "../components/CaseFields";
import type { Patient } from "../api/types";
import { useAuth } from "../lib/auth";
import type { DashboardSummary } from "../api/types";
import { Spinner } from "../components/ui";

export function DashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState<DashboardSummary | null>(null);
  // New case (M4): pick the patient, then what it is about and who looks after it.
  const [newCase, setNewCase] = useState<{ patient: Patient | null; title: string; doctorId: string } | null>(null);
  const [newCaseError, setNewCaseError] = useState<string | null>(null);

  async function openCase() {
    if (!newCase?.patient) return;
    setNewCaseError(null);
    try {
      const created = await createEpisode({ patientId: newCase.patient.id, title: newCase.title, doctorId: newCase.doctorId || null });
      navigate(`/cases/${created.id}`);
    } catch (err) {
      setNewCaseError(describeApiError(err, "Could not open the case."));
    }
  }

  useEffect(() => { getDashboard(user).then(setData).catch(() => {}); }, [user]);

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
        {newCase === null && (
          <button onClick={() => setNewCase({ patient: null, title: "", doctorId: "" })} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover">New case</button>
        )}
      </div>

      {newCase !== null && (
        <form onSubmit={e => { e.preventDefault(); void openCase(); }} className="mt-4 max-w-2xl space-y-4 rounded-xl border border-slate-200 bg-white p-5">
          <PatientSearch selected={newCase.patient} onSelect={p => setNewCase({ ...newCase, patient: p })} />
          {!newCase.patient && user?.role !== "doctor" && (
            <button type="button" onClick={() => navigate("/patients/onboarding")} className="text-sm text-brand hover:underline">Onboard a new patient</button>
          )}
          {newCase.patient && (
            <>
              <div>
                <label htmlFor="dash-case-title" className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Title</label>
                <input id="dash-case-title" value={newCase.title} onChange={e => setNewCase({ ...newCase, title: e.target.value })}
                  placeholder="e.g. Asthma review" className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
              </div>
              <DoctorSelect label="Doctor" value={newCase.doctorId} onChange={v => setNewCase({ ...newCase, doctorId: v })} emptyLabel="The patient's doctor" />
            </>
          )}
          {newCaseError && <p className="text-sm text-red-600">{newCaseError}</p>}
          <div className="flex gap-2">
            <button disabled={!newCase.patient || !newCase.title.trim()} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">Open case</button>
            <button type="button" onClick={() => { setNewCase(null); setNewCaseError(null); }} className="text-sm text-slate-500">Cancel</button>
          </div>
        </form>
      )}

      {!data ? <div className="mt-8"><Spinner /></div> : <>
        <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          {tiles.map(t => (
            <div key={t.key} onClick={() => navigate(t.path)} className={`cursor-pointer rounded-xl border border-slate-200 border-t-2 ${t.color} bg-white p-5 hover:shadow-md transition-shadow`}>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{t.label}</div>
              <div className="mt-2 text-3xl font-bold text-slate-900">{data[t.key] ?? "—"}</div>
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
                  <Tooltip
                    cursor={{ fill: "#f1f5f9" }}
                    formatter={(value: number) => [`${value} appointment${value === 1 ? "" : "s"}`, "Scheduled"]}
                  />
                  <Bar
                    dataKey="value" fill="#0d9488" radius={[3,3,0,0]} barSize={40} cursor="pointer"
                    onClick={(entry: { payload?: { date: string } }) =>
                      entry.payload && navigate("/calendar", { state: { date: entry.payload.date } })}
                  />
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
