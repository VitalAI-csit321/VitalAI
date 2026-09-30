import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { createAppointment, getAvailability } from "../api/appointments";
import { getCase, getPatient, listPatients } from "../api/cases";
import { resolveCaseChoice, staffContactFor } from "../api/episodes";
import { CasePicker } from "../components/CaseFields";
import { listDoctors } from "../api/doctors";
import { isDemoMode } from "../lib/demoMode";
import { ApiError, describeApiError } from "../lib/apiClient";
import { demoPatients } from "../data/demoData";
import type { AppointmentType, Availability, Doctor, Patient } from "../api/types";
import { Spinner } from "../components/ui";
import { TYPE_LABEL, parseClinicDateTime, toDateInputValue, toTimeInputValueClinic } from "../components/calendarHelpers";
import { formatDate, formatTime } from "../lib/format";

const DURATIONS = [15, 30, 45, 60, 90, 120];

export function AppointmentNewPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // caseId: a contact (the inbox's "Book appointment"); episodeId: a case (the case page).
  const prefillCaseId = searchParams.get("caseId");
  const prefillEpisodeId = searchParams.get("episodeId");
  const prefillPatientId = searchParams.get("patientId");
  const prefillReason = searchParams.get("reason");
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [loadingDoctors, setLoadingDoctors] = useState(true);

  const [patientQuery, setPatientQuery] = useState("");
  const [patientResults, setPatientResults] = useState<Patient[]>([]);
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);
  const [caseChoice, setCaseChoice] = useState(prefillEpisodeId ?? "");
  const [newCaseTitle, setNewCaseTitle] = useState("");

  const [appointmentType, setAppointmentType] = useState<AppointmentType>("new_patient");
  const [doctorId, setDoctorId] = useState("");
  // ?date=YYYY-MM-DD from the calendar's day panel; otherwise tomorrow.
  const [date, setDate] = useState(() => {
    const d = searchParams.get("date");
    return d && /^\d{4}-\d{2}-\d{2}$/.test(d) ? d : toDateInputValue(new Date(Date.now() + 86400000));
  });
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

  // Arriving from a task's "Book appointment" action: preselect the patient
  // and carry the request text across so front desk does not retype it.
  useEffect(() => {
    if (prefillReason) setReason(prefillReason);
    if (isDemoMode()) {
      const match = demoPatients.find(p => p.id === prefillPatientId);
      if (match) setSelectedPatient(match);
      return;
    }
    // The inbox only knows the case; the case knows the patient. This used to
    // scan listPatients({limit: 200}), which the API refuses (max 100).
    (async () => {
      const patientId = prefillPatientId ?? (prefillCaseId ? (await getCase(prefillCaseId)).patientId : null);
      if (patientId) setSelectedPatient(await getPatient(patientId));
    })().catch(() => {});
  }, [prefillPatientId, prefillCaseId, prefillReason]);

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
    const start = parseClinicDateTime(date, startTime);
    return formatTime(new Date(start.getTime() + durationMinutes * 60000).toISOString());
  }, [date, startTime, durationMinutes]);

  async function handleSave() {
    if (!selectedPatient || !doctorId || !date || !startTime) {
      setError("Please select a patient, doctor, date and time.");
      return;
    }
    if (repeatOn && repeatOccurrences < 2) {
      // The backend rejects occurrences <= 1 (a "repeat" of one is just a
      // normal booking), but the number input's min={2} doesn't stop someone
      // typing/backspacing below it. Catching it here gives a clear message
      // instead of a raw 422 -- and, critically, avoids silently rounding up
      // to 2 and booking a second appointment nobody asked for.
      setError("Repeat occurrences must be at least 2, or turn off Repeat.");
      return;
    }
    setSaving(true); setError(null);
    try {
      // The backend books against a contact. From the inbox that is the
      // message's own contact (its case comes with it); otherwise the chosen
      // case's contact, which the backend reuses or creates for staff.
      let caseId: string;
      if (prefillCaseId) {
        caseId = prefillCaseId;
      } else if (isDemoMode()) {
        caseId = `demo-case-${selectedPatient.id}`;
      } else {
        const episodeId = await resolveCaseChoice(
          selectedPatient.id, caseChoice, newCaseTitle || reason || `${TYPE_LABEL[appointmentType]} appointment`,
        );
        if (!episodeId) { setError("Choose the case this appointment is for."); return; }
        setCaseChoice(episodeId); // a retry after a clash must not open a second case
        caseId = await staffContactFor(episodeId, "Booked by staff");
      }

      await createAppointment({
        doctorId, caseId, timeSlot: parseClinicDateTime(date, startTime).toISOString(),
        durationMinutes, appointmentType, location: location || undefined,
        reason: reason || undefined, internalNotes: internalNotes || undefined,
        notifyPatient, notifyProvider: notifyReminder,
        repeat: repeatOn ? { intervalDays: repeatIntervalDays, occurrences: repeatOccurrences } : undefined,
      });
      navigate("/calendar");
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 409
          ? "Could not book this appointment. The slot may already be taken."
          : describeApiError(err, "Could not book this appointment."),
      );
    } finally {
      setSaving(false);
    }
  }

  const selectedDoctor = doctors.find(d => d.id === doctorId);

  return (
    <div className="p-6">
      <div className="flex items-center gap-1 text-sm text-slate-500">
        <Link to="/calendar" className="hover:text-slate-700">Calendar</Link> / <span className="text-slate-700">New appointment</span>
      </div>
      <h1 className="mt-3 text-2xl font-bold text-slate-900">New appointment</h1>
      <p className="mt-1 text-sm text-slate-500">Complete the details below to book an appointment.</p>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
          <div>
            <span className="mb-1.5 block text-sm font-medium text-slate-700">Patient</span>
            {selectedPatient ? (
              <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm">
                <span className="text-slate-900">{selectedPatient.name} ({selectedPatient.mrn})</span>
                <button onClick={() => { setSelectedPatient(null); setPatientQuery(""); setCaseChoice(""); }} className="text-xs text-brand hover:underline">Change patient</button>
              </div>
            ) : (
              <div className="relative">
                <input aria-label="Patient" value={patientQuery} onChange={e => setPatientQuery(e.target.value)} placeholder="Search by patient name or MRN"
                  className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
                {patientResults.length > 0 && (
                  <div className="absolute z-10 mt-1 w-full overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
                    {patientResults.map(p => (
                      <button key={p.id} onClick={() => { setSelectedPatient(p); setPatientResults([]); }}
                        className="block w-full px-3.5 py-2 text-left text-sm hover:bg-slate-50">
                        {p.name} <span className="text-slate-400">({p.mrn})</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {selectedPatient && !prefillCaseId && !isDemoMode() && (
            <CasePicker patientId={selectedPatient.id} value={caseChoice} onChange={setCaseChoice}
              newTitle={newCaseTitle} onNewTitle={setNewCaseTitle} />
          )}

          <div>
            <label htmlFor="appt-new-appointment-type" className="mb-1.5 block text-sm font-medium text-slate-700">Appointment type</label>
            <select id="appt-new-appointment-type" value={appointmentType} onChange={e => setAppointmentType(e.target.value as AppointmentType)} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand">
              {(Object.keys(TYPE_LABEL) as AppointmentType[]).map(t => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
            </select>
          </div>

          <div>
            <label htmlFor="appt-new-provider" className="mb-1.5 block text-sm font-medium text-slate-700">Doctor</label>
            {loadingDoctors ? <Spinner /> : (
              <select id="appt-new-provider" value={doctorId} onChange={e => setDoctorId(e.target.value)} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand">
                {doctors.map(d => <option key={d.id} value={d.id}>{d.fullName}</option>)}
              </select>
            )}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="appt-new-date" className="mb-1.5 block text-sm font-medium text-slate-700">Date</label>
              <input id="appt-new-date" type="date" value={date} onChange={e => setDate(e.target.value)} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
            </div>
            <div>
              <label htmlFor="appt-new-start-time" className="mb-1.5 block text-sm font-medium text-slate-700">Start time</label>
              <input id="appt-new-start-time" type="time" value={startTime} onChange={e => setStartTime(e.target.value)} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="appt-new-duration" className="mb-1.5 block text-sm font-medium text-slate-700">Duration</label>
              <select id="appt-new-duration" value={durationMinutes} onChange={e => setDurationMinutes(Number(e.target.value))} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand">
                {DURATIONS.map(d => <option key={d} value={d}>{d} minutes</option>)}
              </select>
            </div>
            <div>
              <span className="mb-1.5 block text-sm font-medium text-slate-700">End time</span>
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm text-slate-500">{endTimeLabel || "Not set"}</div>
            </div>
          </div>

          <div>
            <label htmlFor="appt-new-location" className="mb-1.5 block text-sm font-medium text-slate-700">Location</label>
            <input id="appt-new-location" value={location} onChange={e => setLocation(e.target.value)} placeholder="e.g. Room 3 Level 2" className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
          </div>

          <div>
            <label htmlFor="appt-new-reason-for-visit" className="mb-1.5 block text-sm font-medium text-slate-700">Reason for visit</label>
            <textarea id="appt-new-reason-for-visit" value={reason} onChange={e => setReason(e.target.value)} rows={3} placeholder="Describe the reason for this appointment"
              className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
          </div>

          <div>
            <label htmlFor="appt-new-internal-notes" className="mb-1.5 block text-sm font-medium text-slate-700">Internal notes</label>
            <textarea id="appt-new-internal-notes" value={internalNotes} onChange={e => setInternalNotes(e.target.value)} rows={3} placeholder="Notes visible to staff only"
              className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
          </div>

          <div className="flex items-center justify-between rounded-lg border border-slate-200 px-3.5 py-3">
            <div>
              <div className="text-sm font-medium text-slate-900">Repeat this appointment</div>
              {repeatOn && <div className="mt-1 text-xs text-slate-500">Every {repeatIntervalDays} days, {repeatOccurrences} times total</div>}
            </div>
            <input type="checkbox" aria-label="Repeat this appointment" checked={repeatOn} onChange={e => setRepeatOn(e.target.checked)} className="h-5 w-9 accent-brand" />
          </div>
          {repeatOn && (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="appt-new-repeat-every-days" className="mb-1.5 block text-sm font-medium text-slate-700">Repeat every (days)</label>
                <input id="appt-new-repeat-every-days" type="number" min={1} max={90} value={repeatIntervalDays} onChange={e => setRepeatIntervalDays(Number(e.target.value))} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
              </div>
              <div>
                <label htmlFor="appt-new-occurrences" className="mb-1.5 block text-sm font-medium text-slate-700">Occurrences</label>
                <input id="appt-new-occurrences" type="number" min={2} max={52} value={repeatOccurrences} onChange={e => setRepeatOccurrences(Number(e.target.value))} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
              </div>
            </div>
          )}
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-sm font-semibold text-slate-900">Availability</div>
            <p className="mt-1 text-xs text-slate-500">{selectedDoctor?.fullName ?? "Select a doctor"}, {date ? formatDate(date) : "no date yet"}</p>
            <div className="mt-3 grid grid-cols-2 gap-2">
              {availability?.slots.filter(s => new Date(s.start).getUTCMinutes() === 0 || new Date(s.start).getUTCMinutes() === 30).map(s => {
                const t = new Date(s.start);
                const hhmm = toTimeInputValueClinic(t);
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
              <div className="flex justify-between"><dt className="text-slate-500">Patient</dt><dd className="font-medium text-slate-900">{selectedPatient?.name ?? "Not selected"}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Type</dt><dd className="font-medium text-slate-900">{TYPE_LABEL[appointmentType]}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Doctor</dt><dd className="font-medium text-slate-900">{selectedDoctor?.fullName ?? "Not selected"}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Date</dt><dd className="font-medium text-slate-900">{date}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Time</dt><dd className="font-medium text-slate-900">{startTime && endTimeLabel ? `${startTime} – ${endTimeLabel}` : "Not set"}</dd></div>
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
              <button onClick={handleSave} disabled={saving} className="flex-1 rounded-lg bg-brand py-2.5 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50">{saving ? "Saving…" : "Save appointment"}</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
