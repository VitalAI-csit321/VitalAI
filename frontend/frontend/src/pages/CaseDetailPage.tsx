import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { getCase } from "../api/cases";
import { getConsentForCase } from "../api/consent";
import type { Case, Consent } from "../api/types";
import { StatusBadge, Spinner } from "../components/ui";

export function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [caseData, setCaseData] = useState<Case | null>(null);
  const [consent, setConsent] = useState<Consent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(null);
    Promise.all([getCase(id), getConsentForCase(id)])
      .then(([c, cons]) => { setCaseData(c); setConsent(cons); })
      .catch(() => setError("Could not load this case."))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="p-6"><Spinner label="Loading case..." /></div>;
  if (error || !caseData) return (
    <div className="p-6">
      <p className="text-sm text-red-600">{error ?? "Case not found."}</p>
      <button onClick={() => navigate("/patients")} className="mt-4 text-sm text-brand hover:underline">Back to patients</button>
    </div>
  );

  return (
    <div className="p-6">
      <button onClick={() => navigate(-1)} className="text-sm text-slate-500 hover:text-slate-700">← Back</button>

      <div className="mt-4 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{caseData.contactReason}</h1>
          {caseData.patientId ? (
            <Link to={`/patients/${caseData.patientId}`} className="mt-1 inline-block text-sm text-brand hover:underline">
              {caseData.patientName}
            </Link>
          ) : (
            <p className="mt-1 text-sm text-slate-500">{caseData.patientName}</p>
          )}
        </div>
        <StatusBadge tone="gray">{caseData.status}</StatusBadge>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-4 rounded-xl border border-slate-200 bg-white p-5 max-w-lg text-sm">
        <div><div className="text-xs text-slate-500 uppercase tracking-wide">Contact channel</div><div className="font-medium text-slate-900 mt-0.5 capitalize">{caseData.contactChannel}</div></div>
        <div><div className="text-xs text-slate-500 uppercase tracking-wide">Created</div><div className="font-medium text-slate-900 mt-0.5">{new Date(caseData.createdAt).toLocaleString("en-GB")}</div></div>
      </div>

      {consent && (
        <div className="mt-6 max-w-lg">
          <h2 className="text-sm font-semibold text-slate-900 mb-2">Consent</h2>
          <div className="grid grid-cols-2 gap-4 rounded-xl border border-slate-200 bg-white p-5 text-sm">
            <div><div className="text-xs text-slate-500 uppercase tracking-wide">Type</div><div className="font-medium text-slate-900 mt-0.5 capitalize">{consent.consentType}</div></div>
            <div><div className="text-xs text-slate-500 uppercase tracking-wide">Status</div><div className="mt-0.5"><StatusBadge tone={consent.status === "captured" ? "green" : consent.status === "withdrawn" ? "red" : "amber"}>{consent.status}</StatusBadge></div></div>
            {consent.capturedAt && (
              <div><div className="text-xs text-slate-500 uppercase tracking-wide">Captured</div><div className="font-medium text-slate-900 mt-0.5">{new Date(consent.capturedAt).toLocaleString("en-GB")}</div></div>
            )}
          </div>
        </div>
      )}

      {caseData.notes && (
        <div className="mt-6 max-w-lg">
          <h2 className="text-sm font-semibold text-slate-900 mb-2">Notes</h2>
          <pre className="whitespace-pre-wrap break-words rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700">{caseData.notes}</pre>
        </div>
      )}
    </div>
  );
}
