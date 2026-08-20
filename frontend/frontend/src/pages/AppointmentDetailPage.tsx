import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { cancelAppointment, completeAppointment, getAppointment } from "../api/appointments";
import type { AppointmentDetail } from "../api/types";
import { Avatar, Spinner, StatusBadge } from "../components/ui";
import {
  STATUS_LABEL, STATUS_TONE, TYPE_LABEL,
  formatDateLong, formatTime, patientDisplayName, patientInitials,
} from "../components/calendarHelpers";

function CancelModal({ onClose, onConfirm }: { onClose: () => void; onConfirm: (reason: string) => Promise<void> }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setBusy(true);
    try { await onConfirm(reason); } finally { setBusy(false); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <h2 className="text-lg font-bold text-slate-900">Cancel appointment</h2>
        <p className="mt-1 text-sm text-slate-500">This will notify the patient and cannot be undone.</p>
        <textarea value={reason} onChange={e => setReason(e.target.value)} rows={3} placeholder="Reason for cancelling (optional)"
          className="mt-4 w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
        <div className="mt-5 flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-lg border border-slate-200 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Keep appointment</button>
          <button onClick={confirm} disabled={busy} className="flex-1 rounded-lg bg-red-600 py-2.5 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50">{busy ? "Cancelling…" : "Cancel appointment"}</button>
        </div>
      </div>
    </div>
  );
}

export function AppointmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [appointment, setAppointment] = useState<AppointmentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCancel, setShowCancel] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function reload() {
    if (!id) return;
    setLoading(true); setError(null);
    getAppointment(id).then(setAppointment).catch(() => setError("Could not load this appointment.")).finally(() => setLoading(false));
  }

  useEffect(reload, [id]);

  async function handleComplete() {
    if (!id) return;
    setBusy(true); setActionError(null);
    try { await completeAppointment(id); reload(); }
    catch { setActionError("Could not mark this appointment complete."); }
    finally { setBusy(false); }
  }

  async function handleCancel(reason: string) {
    if (!id) return;
    setActionError(null);
    try { await cancelAppointment(id, reason || undefined); setShowCancel(false); reload(); }
    catch { setActionError("Could not cancel this appointment."); }
  }

  if (loading) return <div className="p-6"><Spinner label="Loading appointment..." /></div>;
  if (error || !appointment) return (
    <div className="p-6">
      <p className="text-sm text-red-600">{error ?? "Appointment not found."}</p>
      <button onClick={() => navigate("/calendar")} className="mt-4 text-sm text-brand hover:underline">Back to calendar</button>
    </div>
  );

  const a = appointment;
  const canCancel = a.status !== "cancelled" && a.status !== "completed";
  const canComplete = a.status === "confirmed";
  const patientName = patientDisplayName(a);

  return (
    <div className="p-6">
      <div className="flex items-center gap-1 text-sm text-slate-500">
        <Link to="/calendar" className="hover:text-slate-700">Calendar</Link> / <span className="text-slate-700">{patientName}</span>
      </div>

      <div className="mt-4 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-slate-900">{TYPE_LABEL[a.appointmentType]}</h1>
          <StatusBadge tone={STATUS_TONE[a.status]}>{STATUS_LABEL[a.status]}</StatusBadge>
        </div>
        <div className="flex gap-2">
          <button onClick={() => navigate(`/calendar/${a.id}/edit`)} className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">Edit</button>
          {canCancel && <button onClick={() => setShowCancel(true)} className="rounded-lg border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50">Cancel Appointment</button>}
          {canComplete && <button onClick={handleComplete} disabled={busy} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50">Mark Complete</button>}
        </div>
      </div>
      {actionError && <p className="mt-2 text-sm text-red-600">{actionError}</p>}

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-6">
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-sm font-semibold text-slate-900">Appointment Details</h2>
            <div className="mt-3 grid grid-cols-2 gap-4 text-sm">
              <div><div className="text-xs uppercase tracking-wide text-slate-400">Date</div><div className="mt-0.5 font-medium text-slate-900">{formatDateLong(a.timeSlot)}</div></div>
              <div><div className="text-xs uppercase tracking-wide text-slate-400">Time</div><div className="mt-0.5 font-medium text-slate-900">{formatTime(a.timeSlot)} to {formatTime(a.endTime)}</div></div>
              <div><div className="text-xs uppercase tracking-wide text-slate-400">Duration</div><div className="mt-0.5 font-medium text-slate-900">{a.durationMinutes} minutes</div></div>
              <div><div className="text-xs uppercase tracking-wide text-slate-400">Type</div><div className="mt-0.5 font-medium text-slate-900">{TYPE_LABEL[a.appointmentType]}</div></div>
              <div><div className="text-xs uppercase tracking-wide text-slate-400">Location</div><div className="mt-0.5 font-medium text-slate-900">{a.location ?? "—"}</div></div>
              <div><div className="text-xs uppercase tracking-wide text-slate-400">Provider</div><div className="mt-0.5 font-medium text-slate-900">{a.doctorName ?? "Unassigned"}</div></div>
              <div><div className="text-xs uppercase tracking-wide text-slate-400">Reference</div><div className="mt-0.5 font-mono text-xs font-medium text-slate-700">{a.referenceCode}</div></div>
            </div>
          </div>

          {a.reason && (
            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <h2 className="text-sm font-semibold text-slate-900">Reason for Visit</h2>
              <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">{a.reason}</p>
            </div>
          )}

          {a.internalNotes && (
            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <h2 className="text-sm font-semibold text-slate-900">Internal Notes</h2>
              <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">{a.internalNotes}</p>
            </div>
          )}

          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-sm font-semibold text-slate-900">Appointment History</h2>
            <div className="mt-3 space-y-3">
              {a.history.length === 0 && <p className="text-sm text-slate-400">No history yet.</p>}
              {a.history.map((h, i) => (
                <div key={i} className="flex items-start gap-3">
                  <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand" />
                  <div>
                    <div className="text-sm text-slate-900">{h.label}</div>
                    <div className="text-xs text-slate-400">{new Date(h.timestamp).toLocaleString("en-GB")}{h.actorLabel ? ` · ${h.actorLabel}` : ""}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="text-sm font-semibold text-slate-900">Patient Information</h2>
          <div className="mt-3 flex items-center gap-3">
            <Avatar initials={patientInitials(patientName)} size={44} />
            <div>
              <div className="font-semibold text-slate-900">{patientName}</div>
              {a.patient?.mrn && <div className="text-xs text-slate-500">{a.patient.mrn}</div>}
            </div>
          </div>
          {a.patient?.id && <Link to={`/patients/${a.patient.id}`} className="mt-2 inline-block text-sm text-brand hover:underline">View full patient record</Link>}

          <dl className="mt-4 space-y-2.5 text-sm">
            {a.patient?.dob && <div><dt className="text-xs uppercase tracking-wide text-slate-400">Date of birth</dt><dd className="mt-0.5 font-medium text-slate-900">{new Date(a.patient.dob).toLocaleDateString("en-GB")}</dd></div>}
            {a.patient?.gender && <div><dt className="text-xs uppercase tracking-wide text-slate-400">Gender</dt><dd className="mt-0.5 font-medium capitalize text-slate-900">{a.patient.gender.replace("_", " ")}</dd></div>}
          </dl>

          {a.consent && (
            <div className="mt-4 rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2.5 text-sm text-emerald-800">
              Consent {a.consent.status}{a.consent.capturedAt ? ` · verified ${new Date(a.consent.capturedAt).toLocaleDateString("en-GB")}` : ""}
              <br />
              <Link to={`/cases/${a.caseId}`} className="text-emerald-700 underline">View consent record</Link>
            </div>
          )}
        </div>
      </div>

      {showCancel && <CancelModal onClose={() => setShowCancel(false)} onConfirm={handleCancel} />}
    </div>
  );
}
