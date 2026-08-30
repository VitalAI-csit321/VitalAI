import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getAppointment, getAvailability, updateAppointment } from "../api/appointments";
import { listDoctors } from "../api/doctors";
import { ApiError, describeApiError } from "../lib/apiClient";
import type { AppointmentDetail, AppointmentStatus, AppointmentType, Availability, Doctor } from "../api/types";
import { Spinner } from "../components/ui";
import { TYPE_LABEL, formatTime, parseClinicDateTime, patientDisplayName, toDateInputValueUTC, toTimeInputValueUTC } from "../components/calendarHelpers";

const DURATIONS = [15, 30, 45, 60, 90, 120];

export function AppointmentEditPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [original, setOriginal] = useState<AppointmentDetail | null>(null);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [appointmentType, setAppointmentType] = useState<AppointmentType>("other");
  const [doctorId, setDoctorId] = useState("");
  const [date, setDate] = useState("");
  const [startTime, setStartTime] = useState(""); // HH:MM
  const [durationMinutes, setDurationMinutes] = useState(30);
  const [location, setLocation] = useState("");
  const [status, setStatus] = useState<AppointmentStatus>("confirmed");
  const [reason, setReason] = useState("");
  const [internalNotes, setInternalNotes] = useState("");
  const [notifyPatient, setNotifyPatient] = useState(true);
  const [notifyProvider, setNotifyProvider] = useState(true);
  const [rescheduleReason, setRescheduleReason] = useState("");

  const [availability, setAvailability] = useState<Availability | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true); setError(null);
    Promise.all([getAppointment(id), listDoctors()])
      .then(([a, docs]) => {
        setOriginal(a); setDoctors(docs);
        setAppointmentType(a.appointmentType); setDoctorId(a.doctorId);
        const d = new Date(a.timeSlot);
        setDate(toDateInputValueUTC(d));
        setStartTime(toTimeInputValueUTC(d));
        setDurationMinutes(a.durationMinutes); setLocation(a.location ?? "");
        setStatus(a.status === "confirmed" || a.status === "pending" ? a.status : "confirmed");
        setReason(a.reason ?? ""); setInternalNotes(a.internalNotes ?? "");
      })
      .catch(() => setError("Could not load this appointment."))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    if (!doctorId || !date) return;
    getAvailability(doctorId, date, durationMinutes <= 30 ? 30 : durationMinutes).then(setAvailability).catch(() => setAvailability(null));
  }, [doctorId, date, durationMinutes]);

  const endTimeLabel = useMemo(() => {
    if (!date || !startTime) return "";
    const start = parseClinicDateTime(date, startTime);
    const end = new Date(start.getTime() + durationMinutes * 60000);
    return formatTime(end.toISOString());
  }, [date, startTime, durationMinutes]);

  const timeChanged = original && (toDateInputValueUTC(new Date(original.timeSlot)) !== date ||
    toTimeInputValueUTC(new Date(original.timeSlot)) !== startTime);

  async function handleSave() {
    if (!id || !date || !startTime) return;
    setSaving(true); setError(null);
    try {
      await updateAppointment(id, {
        doctorId, timeSlot: parseClinicDateTime(date, startTime).toISOString(), durationMinutes,
        appointmentType, location: location || undefined, status, reason: reason || undefined,
        internalNotes: internalNotes || undefined, notifyPatient, notifyProvider,
        rescheduleReason: timeChanged ? (rescheduleReason || undefined) : undefined,
      });
      navigate(`/calendar/${id}`);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 409
          ? "Could not save changes. The slot may already be taken."
          : describeApiError(err, "Could not save changes."),
      );
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="p-6"><Spinner label="Loading appointment..." /></div>;
  if (error && !original) return <div className="p-6"><p className="text-sm text-red-600">{error}</p></div>;
  if (!original) return null;

  return (
    <div className="p-6">
      <div className="flex items-center gap-1 text-sm text-slate-500">
        <Link to="/calendar" className="hover:text-slate-700">Calendar</Link> / <Link to={`/calendar/${id}`} className="hover:text-slate-700">{patientDisplayName(original)}</Link> / <span className="text-slate-700">Edit Appointment</span>
      </div>
      <h1 className="mt-3 text-2xl font-bold text-slate-900">Edit Appointment</h1>
      <p className="mt-1 text-xs text-slate-400">{original.referenceCode}</p>

      <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800">
        Editing this appointment will notify the patient by email if the toggles below are on.
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Patient</label>
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm text-slate-700">{patientDisplayName(original)}{original.patient?.mrn ? ` — ${original.patient.mrn}` : ""}</div>
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Appointment Type</label>
            <select value={appointmentType} onChange={e => setAppointmentType(e.target.value as AppointmentType)} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand">
              {(Object.keys(TYPE_LABEL) as AppointmentType[]).map(t => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Provider</label>
            <select value={doctorId} onChange={e => setDoctorId(e.target.value)} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand">
              {doctors.map(d => <option key={d.id} value={d.id}>{d.fullName}</option>)}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Date</label>
              <input type="date" value={date} onChange={e => setDate(e.target.value)} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Start Time</label>
              <input type="time" value={startTime} onChange={e => setStartTime(e.target.value)} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Duration</label>
              <select value={durationMinutes} onChange={e => setDurationMinutes(Number(e.target.value))} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand">
                {DURATIONS.map(d => <option key={d} value={d}>{d} minutes</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">End Time</label>
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm text-slate-500">{endTimeLabel || "—"}</div>
            </div>
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Location</label>
            <input value={location} onChange={e => setLocation(e.target.value)} placeholder="e.g. Room 3 Level 2" className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Status</label>
            <select value={status} onChange={e => setStatus(e.target.value as AppointmentStatus)} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand">
              <option value="pending">Pending</option>
              <option value="confirmed">Confirmed</option>
            </select>
            <p className="mt-1 text-xs text-slate-400">Use the Cancel/Mark Complete buttons on the appointment page to change those states.</p>
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Reason for Visit</label>
            <textarea value={reason} onChange={e => setReason(e.target.value)} rows={3} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Internal Notes</label>
            <textarea value={internalNotes} onChange={e => setInternalNotes(e.target.value)} rows={3} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex gap-3 pt-2">
            <button onClick={() => navigate(-1)} className="rounded-lg border border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Discard Changes</button>
            <button onClick={handleSave} disabled={saving} className="rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50">{saving ? "Saving…" : "Save Changes"}</button>
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-sm font-semibold text-slate-900">Reschedule Assistant</div>
            <p className="mt-1 text-xs text-slate-500">Pick a date above, then choose an available time.</p>
            <div className="mt-3 grid grid-cols-2 gap-2">
              {availability?.slots.filter(s => new Date(s.start).getUTCMinutes() === 0 || new Date(s.start).getUTCMinutes() === 30).map(s => {
                const t = new Date(s.start);
                const hhmm = toTimeInputValueUTC(t);
                const isCurrent = hhmm === startTime;
                return (
                  <button key={s.start} disabled={!s.available && !isCurrent} onClick={() => setStartTime(hhmm)}
                    className={`rounded-lg border px-2 py-1.5 text-xs font-medium ${isCurrent ? "border-brand bg-brand/10 text-brand" : s.available ? "border-slate-200 text-slate-700 hover:bg-slate-50" : "cursor-not-allowed border-slate-100 text-slate-300 line-through"}`}>
                    {formatTime(s.start)}
                  </button>
                );
              })}
              {!availability && <p className="col-span-2 text-xs text-slate-400">Pick a provider and date to see availability.</p>}
            </div>
            <label className="mt-4 flex items-center justify-between text-sm text-slate-700">
              Notify patient by email
              <input type="checkbox" checked={notifyPatient} onChange={e => setNotifyPatient(e.target.checked)} className="h-4 w-4 accent-brand" />
            </label>
            <label className="mt-2 flex items-center justify-between text-sm text-slate-700">
              Notify provider
              <input type="checkbox" checked={notifyProvider} onChange={e => setNotifyProvider(e.target.checked)} className="h-4 w-4 accent-brand" />
            </label>
            {timeChanged && (
              <div className="mt-3">
                <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Reschedule reason (optional)</label>
                <textarea value={rescheduleReason} onChange={e => setRescheduleReason(e.target.value)} rows={2} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand" />
              </div>
            )}
            <p className="mt-3 text-xs text-slate-400">All changes to this appointment are logged in the VitalAI audit trail.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
