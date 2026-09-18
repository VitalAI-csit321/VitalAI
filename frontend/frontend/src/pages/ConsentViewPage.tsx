import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getConsentForCase, resolveConsentReview } from "../api/consent";
import { getCase } from "../api/cases";
import type { Case, Consent } from "../api/types";
import { StatusBadge, Spinner } from "../components/ui";
import { CLAUSES } from "./ConsentCapturePage";

export function ConsentViewPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const navigate = useNavigate();
  const [caseData, setCaseData] = useState<Case | null>(null);
  const [consent, setConsent] = useState<Consent | null>(null);
  const [checks, setChecks] = useState<{ label: string; checked: boolean }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!caseId) return;
    Promise.all([getCase(caseId), getConsentForCase(caseId)])
      .then(([c, cons]) => { setCaseData(c); setConsent(cons); setChecks(cons?.formSnapshot?.checks ?? []); })
      .catch(() => setError("Could not load this consent record."))
      .finally(() => setLoading(false));
  }, [caseId]);

  if (loading) return <div className="p-6"><Spinner label="Loading consent..." /></div>;
  if (error || !consent) return (
    <div className="p-6">
      <p className="text-sm text-red-600">{error ?? "Consent record not found."}</p>
      <button onClick={() => navigate("/consent")} className="mt-4 text-sm text-brand hover:underline">Back to queue</button>
    </div>
  );

  // Gate editability on the server-confirmed snapshot, not the in-progress
  // `checks` edits - otherwise ticking the last box flips this false (and
  // hides the save button) before the user ever gets to save.
  const canEditChecklist =
    consent.status === "captured" && (consent.formSnapshot?.checks.some((c) => !c.checked) ?? false);

  async function saveChecklist() {
    if (!consent?.formSnapshot) return;
    setSaving(true); setSaveError(null);
    try {
      const updated = await resolveConsentReview(consent.id, { ...consent.formSnapshot, checks });
      setConsent(updated);
    } catch {
      setSaveError("Could not save the checklist. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="p-6">
      <button onClick={() => navigate("/consent")} className="text-sm text-slate-500 hover:text-slate-700">← Back to queue</button>

      <div className="mt-4 flex items-start justify-between">
        <h1 className="text-2xl font-bold text-slate-900">{caseData?.patientName ?? "Consent record"}</h1>
        <StatusBadge tone={canEditChecklist ? "amber" : consent.status === "captured" ? "green" : consent.status === "withdrawn" ? "red" : "amber"}>
          {canEditChecklist ? "review" : consent.status}
        </StatusBadge>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="rounded-xl border border-slate-200 bg-white p-6">
          <h2 className="font-semibold text-slate-900 capitalize">{consent.consentType.replace(/_/g, " ")}</h2>
          <div className="mt-4 space-y-4">{CLAUSES.map((c, i) => <p key={i} className="text-sm text-slate-700">{i + 1}. {c}</p>)}</div>
          <div className="my-5 h-px bg-slate-100" />
          {checks.length > 0 ? (
            <div className="space-y-3">
              {checks.map((check, i) => (
                <label key={check.label} className="flex items-start gap-3 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={check.checked}
                    disabled={!canEditChecklist}
                    onChange={() => canEditChecklist && setChecks((cs) => cs.map((c, idx) => idx === i ? { ...c, checked: !c.checked } : c))}
                    className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand"
                  />
                  {check.label}
                </label>
              ))}
              {canEditChecklist && (
                <div className="pt-2">
                  <button onClick={saveChecklist} disabled={saving} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50">
                    {saving ? "Saving…" : "Complete consent"}
                  </button>
                  {saveError && <p className="mt-2 text-sm text-red-600">{saveError}</p>}
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-slate-500">No form details were recorded for this consent.</p>
          )}
        </div>
        <div className="space-y-5">
          <div className="rounded-xl border border-slate-200 bg-white p-6">
            <h2 className="font-semibold text-slate-900 mb-4">Signature</h2>
            {consent.formSnapshot?.signature ? (
              <img src={consent.formSnapshot.signature} alt="Patient signature" className="h-40 w-full rounded-lg border border-slate-200 bg-slate-50 object-contain" />
            ) : (
              <div className="flex h-40 w-full items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-sm text-slate-400">No signature recorded</div>
            )}
          </div>
          {consent.capturedAt && (
            <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm">
              <div className="text-xs text-slate-500 uppercase tracking-wide">Captured</div>
              <div className="mt-0.5 font-medium text-slate-900">{new Date(consent.capturedAt).toLocaleString("en-GB")}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
