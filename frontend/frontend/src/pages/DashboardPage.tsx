import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getDashboard } from "../api/misc";
import { createEpisode } from "../api/episodes";
import { describeApiError } from "../lib/apiClient";
import { DoctorSelect, PatientSearch } from "../components/CaseFields";
import type { Patient } from "../api/types";
import { useAuth } from "../lib/auth";
import type { DashboardSummary } from "../api/types";
import { Spinner, StatusBadge } from "../components/ui";
import { STATUS_LABEL, STATUS_TONE, TYPE_LABEL, patientDisplayName } from "../components/calendarHelpers";
import { formatTime } from "../lib/format";
import { timeAgo } from "../lib/time";

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
  const now = new Date().toISOString();
  const nextAppointment = data?.today.find(a => a.timeSlot >= now) ?? null;

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
                <label htmlFor="dash-case-title" className="mb-1.5 block text-xs font-semibold text-slate-500">Title</label>
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
        <div className="mt-6 grid grid-cols-4 overflow-hidden rounded-xl border border-slate-200 bg-white">
          <Stat label="Appointments today" value={data.today.length} to="/calendar" accent="border-t-brand"
            note={nextAppointment ? `Next at ${formatTime(nextAppointment.timeSlot)}, ${nextAppointment.doctorName ?? "no doctor"}` : "None left today"} />
          <Stat label="Awaiting approval" value={data.awaitingApproval} to="/review-queue" accent="border-t-amber-400"
            note={data.oldestAwaiting ? `Oldest ${timeAgo(data.oldestAwaiting)}` : "All clear"} />
          <Stat label="Escalated" value={data.escalations} to="/escalations" accent="border-t-red-400"
            note={data.escalations === null ? "Not in your queues" : data.oldestEscalated ? `Oldest ${timeAgo(data.oldestEscalated)}` : "None"} />
          <Stat label="Open cases" value={data.openCases} to="/patients" accent="border-t-brand"
            note={user?.role === "doctor" ? "Your patients" : "Across all patients"} />
        </div>

        <div className="mt-6 grid grid-cols-2 gap-6">
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-base font-semibold text-slate-900">Appointments this week</h2>
            <div className="mt-4 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.workflowByDay} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
                  <CartesianGrid strokeDasharray="4 4" stroke="#e2e8f0" vertical={false} />
                  <XAxis dataKey="day" tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 12 }} />
                  <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "#64748b", fontSize: 12 }} />
                  <Tooltip
                    cursor={{ fill: "#f1f5f9" }}
                    formatter={(value: number) => [`${value} appointment${value === 1 ? "" : "s"}`, "Scheduled"]}
                  />
                  <Bar
                    dataKey="value" name="Appointments" fill="#0d9488" radius={[3,3,0,0]} barSize={40} cursor="pointer"
                    onClick={(entry: { payload?: { date: string } }) =>
                      entry.payload && navigate("/calendar", { state: { date: entry.payload.date } })}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <section className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="flex items-baseline justify-between">
              <h2 className="text-base font-semibold text-slate-900">Needs attention</h2>
              <Link to="/review-queue" className="text-sm font-medium text-brand hover:underline">Open review queue</Link>
            </div>
            {data.attention.length === 0 ? (
              <p className="mt-4 text-sm text-slate-500">Nothing is waiting for you.</p>
            ) : (
              <ul className="mt-3 divide-y divide-slate-100">
                {data.attention.map(item => (
                  <li key={item.id}>
                    <Link to={item.href} className="flex items-start justify-between gap-4 rounded-lg px-2 py-3 hover:bg-slate-50">
                      <div className="min-w-0">
                        {item.urgency && (
                          <p className="text-xs font-semibold text-red-700">{item.urgency === "urgent" ? "Urgent" : "High priority"}</p>
                        )}
                        <p className="truncate text-sm font-medium text-slate-900">{item.title}</p>
                        <p className="truncate text-xs text-slate-500">{item.kind}</p>
                      </div>
                      <span className="shrink-0 text-xs text-slate-500">{timeAgo(item.createdAt)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <section className="mt-6 rounded-xl border border-slate-200 bg-white p-5">
          <div className="flex items-baseline justify-between">
            <h2 className="text-base font-semibold text-slate-900">Today's appointments</h2>
            <Link to="/calendar" className="text-sm font-medium text-brand hover:underline">Open calendar</Link>
          </div>
          {data.today.length === 0 ? (
            <p className="mt-4 text-sm text-slate-500">No appointments today.</p>
          ) : (
            <table className="mt-3 w-full text-sm">
              <thead className="text-left text-xs font-medium text-slate-500">
                <tr className="border-b border-slate-200">
                  <th scope="col" className="py-2 pr-4">Time</th>
                  <th scope="col" className="py-2 pr-4">Patient</th>
                  <th scope="col" className="py-2 pr-4">Doctor</th>
                  <th scope="col" className="py-2 pr-4">Type</th>
                  <th scope="col" className="py-2">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.today.map(a => (
                  <tr key={a.id} onClick={() => navigate(`/calendar/${a.id}`)} className="cursor-pointer hover:bg-slate-50">
                    <td className="whitespace-nowrap py-2.5 pr-4 font-medium text-slate-900">{formatTime(a.timeSlot)}</td>
                    <td className="py-2.5 pr-4 text-slate-700">{patientDisplayName(a)}</td>
                    <td className="py-2.5 pr-4 text-slate-700">{a.doctorName ?? "Unassigned"}</td>
                    <td className="py-2.5 pr-4 text-slate-700">{TYPE_LABEL[a.appointmentType]}</td>
                    <td className="py-2.5"><StatusBadge tone={STATUS_TONE[a.status]}>{STATUS_LABEL[a.status]}</StatusBadge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </>}
    </div>
  );
}

// One number in the dashboard's summary row; the whole cell opens its page.
function Stat({ label, value, note, to, accent }: { label: string; value: number | null; note: string; to: string; accent: string }) {
  return (
    <Link to={to} className={`block border-l border-t-2 border-l-slate-200 px-5 py-4 first:border-l-0 hover:bg-slate-50 ${accent}`}>
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-900">{value ?? "N/A"}</p>
      <p className="mt-0.5 text-xs text-slate-500">{note}</p>
    </Link>
  );
}
