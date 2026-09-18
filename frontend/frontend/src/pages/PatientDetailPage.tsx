import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { getPatient, listCasesForPatient } from "../api/cases";
import { listAppointments } from "../api/appointments";
import { listClinicalDocuments, openClinicalDocument } from "../api/records";
import { listConsentsForPatient, consentTypeLabel } from "../api/consent";
import type { Patient, Case, Appointment, ClinicalDocument, Consent } from "../api/types";
import { StatusBadge, Spinner } from "../components/ui";
import { PROFILE_FIELD_GROUPS, PROFILE_FIELD_LABELS_BY_API_KEY } from "../components/patientProfileFields";
import { useAuth } from "../lib/auth";

export function PatientDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  // Doctors get view_clinical as a role default; operators/admins only via an
  // explicit grant (user.grantedPermissions is extras on top of the role, see
  // CurrentUser) - either way is enough to open a document, matching the
  // backend's can_read_clinical. Everyone who can see the list at all (also
  // gated on the backend, separately, via can_list_clinical) sees the names.
  const canOpenDocuments = user?.role === "doctor" || (user?.grantedPermissions.includes("view_clinical") ?? false);
  const [patient, setPatient] = useState<Patient | null>(null);
  const [cases, setCases] = useState<Case[]>([]);
  const [casesError, setCasesError] = useState<string | null>(null);
  const [consents, setConsents] = useState<Consent[]>([]);
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [appointmentsError, setAppointmentsError] = useState<string | null>(null);
  const [documents, setDocuments] = useState<ClinicalDocument[]>([]);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [openingDocumentId, setOpeningDocumentId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(null);
    getPatient(id)
      .then(setPatient)
      .catch(() => setError("Could not load this patient."))
      .finally(() => setLoading(false));

    setCasesError(null);
    listCasesForPatient(id)
      .then(setCases)
      .catch(() => setCasesError("Could not load onboarding cases for this patient."));

    listConsentsForPatient(id)
      .then(setConsents)
      .catch(() => setConsents([]));

    setAppointmentsError(null);
    listAppointments({ patientId: id, limit: 100 })
      .then(r => setAppointments(r.items))
      .catch(() => setAppointmentsError("Could not load appointments for this patient."));

    setDocumentsError(null);
    listClinicalDocuments(id)
      .then(setDocuments)
      .catch(() => setDocumentsError("Not permitted to view clinical documents for this patient."));
  }, [id]);

  async function handleOpenDocument(documentId: string) {
    setOpeningDocumentId(documentId);
    try {
      await openClinicalDocument(documentId);
    } catch {
      setDocumentsError("Could not open this document.");
    } finally {
      setOpeningDocumentId(null);
    }
  }

  if (loading) return <div className="p-6"><Spinner label="Loading patient..." /></div>;
  if (error || !patient) return (
    <div className="p-6">
      <p className="text-sm text-red-600">{error ?? "Patient not found."}</p>
      <button onClick={() => navigate("/patients")} className="mt-4 text-sm text-brand hover:underline">Back to patients</button>
    </div>
  );

  const values = patient as unknown as Record<string, string | null>;

  const historyRows = [
    ...cases.map(c => ({
      key: `case-${c.id}`,
      reason: c.contactReason,
      channel: c.contactChannel,
      status: c.status,
      created: c.createdAt,
      action: <Link to={`/cases/${c.id}`} className="text-brand font-medium hover:underline">Open case</Link>,
    })),
    ...consents.map(cons => ({
      key: `consent-${cons.id}`,
      reason: `Consent - ${consentTypeLabel(cons.consentType)}`,
      channel: "—",
      status: cons.status,
      created: cons.createdAt,
      action: <Link to={`/consent/${cons.caseId}/view`} className="text-brand font-medium hover:underline">View</Link>,
    })),
  ].sort((a, b) => new Date(b.created).getTime() - new Date(a.created).getTime());

  return (
    <div className="p-6">
      <button onClick={() => navigate("/patients")} className="text-sm text-slate-500 hover:text-slate-700">← Back to patients</button>

      <div className="mt-4 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{patient.name}</h1>
          <p className="mt-1 text-sm text-slate-500 font-mono">{patient.mrn}</p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge tone={patient.status === "active" ? "green" : patient.status === "pending" ? "amber" : "gray"}>{patient.status}</StatusBadge>
          <button onClick={() => navigate(`/patients/${patient.id}/edit`)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">Edit</button>
        </div>
      </div>

      {patient.missingFields.length > 0 && (
        <div className="mt-4 max-w-lg rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Pending — missing: {patient.missingFields.map(f => PROFILE_FIELD_LABELS_BY_API_KEY[f] ?? f).join(", ")}
        </div>
      )}

      <div className="mt-6 grid grid-cols-2 gap-4 rounded-xl border border-slate-200 bg-white p-5 max-w-lg text-sm">
        <div><div className="text-xs text-slate-500 uppercase tracking-wide">Date of birth</div><div className="font-medium text-slate-900 mt-0.5">{patient.dob ? new Date(patient.dob).toLocaleDateString("en-GB") : "—"}</div></div>
        <div><div className="text-xs text-slate-500 uppercase tracking-wide">Gender</div><div className="font-medium text-slate-900 mt-0.5 capitalize">{patient.gender?.replace("_", " ") ?? "—"}</div></div>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2 max-w-4xl">
        {PROFILE_FIELD_GROUPS.map(group => (
          <div key={group.title} className="rounded-xl border border-slate-200 bg-white p-5 text-sm">
            <h2 className="text-sm font-semibold text-slate-900 mb-3">{group.title}</h2>
            <div className="space-y-3">
              {group.fields.map(def => (
                <div key={def.key}>
                  <div className="text-xs text-slate-500 uppercase tracking-wide">{def.label}</div>
                  <div className="font-medium text-slate-900 mt-0.5 whitespace-pre-line">{values[def.key] || "Not provided"}</div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-6">
        <h2 className="text-sm font-semibold text-slate-900 mb-3">Appointments</h2>
        {appointmentsError ? (
          <p className="text-sm text-red-600">{appointmentsError}</p>
        ) : appointments.length === 0 ? (
          <p className="text-sm text-slate-500">No appointments yet for this patient.</p>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {["Date", "Doctor", "Type", "Status", "Reason", ""].map(h => <th key={h} className="px-6 py-3">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {appointments.map(a => (
                  <tr key={a.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    <td className="px-6 py-4 text-slate-900">{new Date(a.timeSlot).toLocaleString("en-GB")}</td>
                    <td className="px-6 py-4 text-slate-600">{a.doctorName ?? "—"}</td>
                    <td className="px-6 py-4 text-slate-600 capitalize">{a.appointmentType.replace(/_/g, " ")}</td>
                    <td className="px-6 py-4"><StatusBadge tone="gray">{a.status}</StatusBadge></td>
                    <td className="px-6 py-4 text-slate-600">{a.reason ?? "—"}</td>
                    <td className="px-6 py-4"><Link to={`/calendar/${a.id}`} className="text-brand font-medium hover:underline">Open</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="mt-6">
        <h2 className="text-sm font-semibold text-slate-900 mb-3">Clinical documents</h2>
        {documentsError ? (
          <p className="text-sm text-red-600">{documentsError}</p>
        ) : documents.length === 0 ? (
          <p className="text-sm text-slate-500">No clinical documents on file for this patient.</p>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {["Type", "Filename", "Date", "Status"].map(h => <th key={h} className="px-6 py-3">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {documents.map(d => (
                  <tr key={d.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    <td className="px-6 py-4 text-slate-900 capitalize">{d.docType.replace(/_/g, " ")}</td>
                    <td className="px-6 py-4">
                      {canOpenDocuments ? (
                        <button
                          onClick={() => handleOpenDocument(d.id)}
                          disabled={openingDocumentId === d.id}
                          className="text-brand font-medium hover:underline disabled:opacity-50"
                        >
                          {openingDocumentId === d.id ? "Opening…" : d.filename}
                        </button>
                      ) : (
                        <span className="text-slate-600" title="Only doctors can open clinical documents">{d.filename}</span>
                      )}
                    </td>
                    <td className="px-6 py-4 text-slate-600">{new Date(d.createdAt).toLocaleDateString("en-GB")}</td>
                    <td className="px-6 py-4">
                      {d.ingestedAt ? <StatusBadge tone="green">Ingested</StatusBadge> : <StatusBadge tone="amber">Not ingested</StatusBadge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="mt-6">
        <h2 className="text-sm font-semibold text-slate-900 mb-3">Onboarding</h2>
        {casesError ? (
          <p className="text-sm text-red-600">{casesError}</p>
        ) : historyRows.length === 0 ? (
          <p className="text-sm text-slate-500">No intake cases yet for this patient.</p>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {["Reason", "Channel", "Status", "Created", ""].map(h => <th key={h} className="px-6 py-3">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {historyRows.map(r => (
                  <tr key={r.key} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    <td className="px-6 py-4 text-slate-900">{r.reason}</td>
                    <td className="px-6 py-4 text-slate-600 capitalize">{r.channel}</td>
                    <td className="px-6 py-4"><StatusBadge tone="gray">{r.status}</StatusBadge></td>
                    <td className="px-6 py-4 text-slate-600">{new Date(r.created).toLocaleDateString("en-GB")}</td>
                    <td className="px-6 py-4">{r.action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
