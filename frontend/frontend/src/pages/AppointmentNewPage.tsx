import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createAppointment, getAvailability } from "../api/appointments";
import { findLatestCaseForPatient, createCase, listPatients } from "../api/cases";
import { listDoctors } from "../api/doctors";
import { isDemoMode } from "../lib/demoMode";
import { demoPatients } from "../data/demoData";
import type { AppointmentType, Availability, Doctor, Patient } from "../api/types";
import { Spinner } from "../components/ui";
import { TYPE_LABEL, formatTime, toDateInputValue } from "../components/calendarHelpers";

const DURATIONS = [15, 30, 45, 60, 90, 120];

export function AppointmentNewPage() {
  const navigate = useNavigate();
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [loadingDoctors, setLoadingDoctors] = useState(true);

  const [patientQuery, setPatientQuery] = useState("");
  const [patientResults, setPatientResults] = useState<Patient[]>([]);
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);

  const [appointmentType, setAppointmentType] = useState<AppointmentType>("new_patient");
  const [doctorId, setDoctorId] = useState("");
  const [date, setDate] = useState(toDateInputValue(new Date(Date.now() + 86400000)));
  const [startTime, setStartTime] = useState("09:00");
  const [durationMinutes, setDurationMinutes] = useState(30);
  const [location, setLocation] = useState("");
  const [reason, setReason] = useState("");
  const [internalNotes, setInternalNotes] = useState("");
  const [repeatOn, setRepeatOn] = useState(false);
  const [repeatIntervalDays, setRepeatIntervalDays] = useState(7);
  const [repeatOccurrences, setRepeatOccurrences] = useState(4);
  const [notifyPatient, setNotifyPatient] = useState(true);
  const [notifyReminder, setNotifyReminder] = useState(true);

  const [availability, setAvailability] = useState<Availability | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listDoctors().then(docs => { setDoctors(docs); if (docs[0]) setDoctorId(docs[0].id); }).catch(() => {}).finally(() => setLoadingDoctors(false));
  }, []);

  useEffect(() => {
    if (patientQuery.trim().length < 2) { setPatientResults([]); return; }
    if (isDemoMode()) {
      const q = patientQuery.toLowerCase();
      setPatientResults(demoPatients.filter(p => p.name.toLowerCase().includes(q) || p.mrn.toLowerCase().includes(q)));
      return;
    }
    const t = setTimeout(() => {
      listPatients({ search: patientQuery, limit: 8 }).then(res => setPatientResults(res.items)).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [patientQuery]);

  useEffect(() => {
    if (!doctorId || !date) return;
    getAvailability(doctorId, date, durationMinutes <= 30 ? 30 : durationMinutes).then(setAvailability).catch(() => setAvailability(null));
  }, [doctorId, date, durationMinutes]);

  const endTimeLabel = useMemo(() => {
    if (!date || !startTime) return "";
    const start = new Date(`${date}T${startTime}:00`);
    return formatTime(new Date(start.getTime() + durationMinutes * 60000).toISOString());
  }, [date, startTime, durationMinutes]);

  async function handleSave() {
    if (!selectedPatient || !doctorId || !date || !startTime) {
      setError("Please select a patient, provider, date and time.");
      return;
    }
    setSaving(true); setError(null);
    try {
      // The backend books against an intake case, not a patient directly.
      // The calendar UI only exposes patient search, so reuse the patient's
      // most recent case, or open a lightweight new one for this booking.
      let caseId: string;
      if (isDemoMode()) {
        caseId = `demo-case-${selectedPatient.id}`;
      } else {
        const existingCase = await findLatestCaseForPatient(selectedPatient.id);
        if (existingCase) {
          caseId = existingCase.id;
        } else {
          const newCase = await createCase({
            patient_name: selectedPatient.name,
            contact_reason: reason || `${TYPE_LABEL[appointmentType]} appointment`,
            contact_channel: "calendar",
          });
          caseId = newCase.id;
        }
      }

      await createAppointment({
        doctorId, caseId, timeSlot: new Date(`${date}T${startTime}:00`).toISOString(),
        durationMinutes, appointmentType, location: location || undefined,
        reason: reason || undefined, internalNotes: internalNotes || undefined,
        notifyPatient, notifyProvider: notifyReminder,
        repeat: repeatOn ? { intervalDays: repeatIntervalDays, occurrences: repeatOccurrences } : undefined,
      });
      navigate("/calendar");
    } catch {
      setError("Could not book this appointment. The slot may already be taken.");
    } finally {
      setSaving(false);
    }
  }

  const selectedDoctor = doctors.find(d => d.id === doctorId);

  return (
    <div className="p-6">
      <div className="flex items-center gap-1 text-sm text-slate-500">
        <Link to="/calendar" className="hover:text-slate-700">Calendar</Link> / <span className="text-slate-700">New Appointment</span>
      </div>
      <h1 className="mt-3 text-2xl font-bold text-slate-900">New Appointment</h1>
      <p className="mt-1 text-sm text-slate-500">Complete the details below to book an appointment.</p>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Patient</label>
            {selectedPatient ? (
              <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm">
                <span className="text-slate-900">{selectedPatient.name} — {selectedPatient.mrn}</span>
                <button onClick={() => { setSelectedPatient(null); setPatientQuery(""); }} className="text-xs text-brand hover:underline">Change patient</button>
              </div>
            ) : (
              <div className="relative">
                <input value={patientQuery} onChange={e => setPatientQuery(e.target.value)} placeholder="Search by patient name or MRN"
                  className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
                {patientResults.length > 0 && (
                  <div className="absolute z-10 mt-1 w-full overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
                    {patientResults.map(p => (
                      <button key={p.id} onClick={() => { setSelectedPatient(p); setPatientResults([]); }}
                        className="block w-full px-3.5 py-2 text-left text-sm hover:bg-slate-50">
                        {p.name} <span className="text-slate-400">— {p.mrn}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Appointment Type</label>
            <select value={appointmentType} onChange={e => setAppointmentType(e.target.value as AppointmentType)} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand">
              {(Object.keys(TYPE_LABEL) as AppointmentType[]).map(t => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
            </select>
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Provider</label>
            {loadingDoctors ? <Spinner /> : (
              <select value={doctorId} onChange={e => setDoctorId(e.target.value)} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand">
                {doctors.map(d => <option key={d.id} value={d.id}>{d.fullName}</option>)}
              </select>
            )}
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
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Reason for Visit</label>
            <textarea value={reason} onChange={e => setReason(e.target.value)} rows={3} placeholder="Describe the reason for this appointment"
              className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Internal Notes</label>
            <textarea value={internalNotes} onChange={e => setInternalNotes(e.target.value)} rows={3} placeholder="Notes visible to staff only"
              className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
          </div>

          <div className="flex items-center justify-between rounded-lg border border-slate-200 px-3.5 py-3">
            <div>
              <div className="text-sm font-medium text-slate-900">Repeat this appointment</div>
              {repeatOn && <div className="mt-1 text-xs text-slate-500">Every {repeatIntervalDays} days, {repeatOccurrences} times total</div>}
            </div>
            <input type="checkbox" checked={repeatOn} onChange={e => setRepeatOn(e.target.checked)} className="h-5 w-9 accent-brand" />
          </div>
          {repeatOn && (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Repeat every (days)</label>
                <input type="number" min={1} max={90} value={repeatIntervalDays} onChange={e => setRepeatIntervalDays(Number(e.target.value))} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Occurrences</label>
                <input type="number" min={2} max={52} value={repeatOccurrences} onChange={e => setRepeatOccurrences(Number(e.target.value))} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
              </div>
            </div>
          )}
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-sm font-semibold text-slate-900">Availability Check</div>
            <p className="mt-1 text-xs text-slate-500">{selectedDoctor?.fullName ?? "Select a provider"} · {date}</p>
            <div className="mt-3 grid grid-cols-2 gap-2">
              {availability?.slots.filter(s => new Date(s.start).getMinutes() === 0 || new Date(s.start).getMinutes() === 30).map(s => {
                const t = new Date(s.start);
                const hhmm = `${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`;
                const isSelected = hhmm === startTime;
                return (
                  <button key={s.start} disabled={!s.available && !isSelected} onClick={() => setStartTime(hhmm)}
                    className={`rounded-lg border px-2 py-1.5 text-xs font-medium ${isSelected ? "border-brand bg-brand/10 text-brand" : s.available ? "border-slate-200 text-slate-700 hover:bg-slate-50" : "cursor-not-allowed border-slate-100 text-slate-300 line-through"}`}>
                    {formatTime(s.start)}
                  </button>
                );
              })}
              {!availability && <p className="col-span-2 text-xs text-slate-400">Pick a provider and date to see availability.</p>}
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
            <div className="font-semibold text-slate-900">Summary</div>
            <dl className="mt-3 space-y-1.5">
              <div className="flex justify-between"><dt className="text-slate-500">Patient</dt><dd className="font-medium text-slate-900">{selectedPatient?.name ?? "—"}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Type</dt><dd className="font-medium text-slate-900">{TYPE_LABEL[appointmentType]}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Provider</dt><dd className="font-medium text-slate-900">{selectedDoctor?.fullName ?? "—"}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Date</dt><dd className="font-medium text-slate-900">{date}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Time</dt><dd className="font-medium text-slate-900">{startTime && endTimeLabel ? `${startTime} – ${endTimeLabel}` : "—"}</dd></div>
              {location && <div className="flex justify-between"><dt className="text-slate-500">Location</dt><dd className="font-medium text-slate-900">{location}</dd></div>}
            </dl>
            <label className="mt-4 flex items-center justify-between">
              Send email confirmation
              <input type="checkbox" checked={notifyPatient} onChange={e => setNotifyPatient(e.target.checked)} className="h-4 w-4 accent-brand" />
            </label>
            <label className="mt-2 flex items-center justify-between">
              Send reminder 24h before
              <input type="checkbox" checked={notifyReminder} onChange={e => setNotifyReminder(e.target.checked)} className="h-4 w-4 accent-brand" />
            </label>
            {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
            <div className="mt-4 flex gap-3">
              <button onClick={() => navigate("/calendar")} className="flex-1 rounded-lg border border-slate-200 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
              <button onClick={handleSave} disabled={saving} className="flex-1 rounded-lg bg-brand py-2.5 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50">{saving ? "Saving…" : "Save Appointment"}</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
