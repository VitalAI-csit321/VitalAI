import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { getPatient, listCasesForPatient } from "../api/cases";
import type { Patient, Case } from "../api/types";
import { StatusBadge, Spinner } from "../components/ui";

export function PatientDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [patient, setPatient] = useState<Patient | null>(null);
  const [cases, setCases] = useState<Case[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(null);
    Promise.all([getPatient(id), listCasesForPatient(id)])
      .then(([p, c]) => { setPatient(p); setCases(c); })
      .catch(() => setError("Could not load this patient."))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="p-6"><Spinner label="Loading patient..." /></div>;
  if (error || !patient) return (
    <div className="p-6">
      <p className="text-sm text-red-600">{error ?? "Patient not found."}</p>
      <button onClick={() => navigate("/patients")} className="mt-4 text-sm text-brand hover:underline">Back to patients</button>
    </div>
  );

  return (
    <div className="p-6">
      <button onClick={() => navigate("/patients")} className="text-sm text-slate-500 hover:text-slate-700">← Back to patients</button>

      <div className="mt-4 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{patient.name}</h1>
          <p className="mt-1 text-sm text-slate-500 font-mono">{patient.mrn}</p>
        </div>
        <StatusBadge tone={patient.status === "active" ? "green" : patient.status === "pending" ? "amber" : "gray"}>{patient.status}</StatusBadge>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-4 rounded-xl border border-slate-200 bg-white p-5 max-w-lg text-sm">
        <div><div className="text-xs text-slate-500 uppercase tracking-wide">Date of birth</div><div className="font-medium text-slate-900 mt-0.5">{patient.dob ? new Date(patient.dob).toLocaleDateString("en-GB") : "—"}</div></div>
        <div><div className="text-xs text-slate-500 uppercase tracking-wide">Gender</div><div className="font-medium text-slate-900 mt-0.5 capitalize">{patient.gender?.replace("_", " ") ?? "—"}</div></div>
      </div>

      <div className="mt-6">
        <h2 className="text-sm font-semibold text-slate-900 mb-3">Case history</h2>
        {cases.length === 0 ? (
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
                {cases.map(c => (
                  <tr key={c.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    <td className="px-6 py-4 text-slate-900">{c.contactReason}</td>
                    <td className="px-6 py-4 text-slate-600 capitalize">{c.contactChannel}</td>
                    <td className="px-6 py-4"><StatusBadge tone="gray">{c.status}</StatusBadge></td>
                    <td className="px-6 py-4 text-slate-600">{new Date(c.createdAt).toLocaleDateString("en-GB")}</td>
                    <td className="px-6 py-4"><Link to={`/cases/${c.id}`} className="text-brand font-medium hover:underline">Open case</Link></td>
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
