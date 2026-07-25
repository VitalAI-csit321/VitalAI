import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createPatientFromOnboarding } from "../api/cases";

const STEPS = ["Details", "Contact", "History", "Insurance", "Review"];

interface FormData {
  // Step 1
  firstName: string; lastName: string; dateOfBirth: string;
  gender: string; address: string; indigenousStatus: string; preferredLanguage: string;
  // Step 2
  phone: string; email: string; emergencyContactName: string; emergencyContactPhone: string;
  preferredCommunication: string; bestTimeToContact: string;
  // Step 3
  knownConditions: string; currentMedications: string; allergies: string;
  // Step 4
  insuranceProvider: string; policyNumber: string; groupNumber: string;
  expiryDate: string; medicareNumber: string; concessionCard: string;
  // Step 5
  confirmed: boolean;
}

const EMPTY: FormData = {
  firstName: "", lastName: "", dateOfBirth: "", gender: "", address: "",
  indigenousStatus: "", preferredLanguage: "",
  phone: "", email: "", emergencyContactName: "", emergencyContactPhone: "",
  preferredCommunication: "", bestTimeToContact: "",
  knownConditions: "", currentMedications: "", allergies: "",
  insuranceProvider: "", policyNumber: "", groupNumber: "",
  expiryDate: "", medicareNumber: "", concessionCard: "None",
  confirmed: false,
};

const inputClass = "w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm outline-none focus:border-brand focus:ring-1 focus:ring-brand";
const labelClass = "block text-sm font-medium text-slate-700 mb-1.5";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><label className={labelClass}>{label}</label>{children}</div>;
}

function Stepper({ current }: { current: number }) {
  return (
    <div className="flex items-center">
      {STEPS.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <div key={label} className="flex items-center">
            <div className="flex flex-col items-center">
              <div className={`flex h-10 w-10 items-center justify-center rounded-full border-2 text-sm font-semibold transition-colors ${
                done ? "border-brand bg-brand text-white" : active ? "border-brand text-brand" : "border-slate-300 text-slate-400"
              }`}>
                {done ? <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg> : i + 1}
              </div>
              <span className={`mt-1.5 text-xs font-medium ${active ? "text-slate-900" : done ? "text-brand" : "text-slate-400"}`}>{label}</span>
            </div>
            {i < STEPS.length - 1 && <div className={`mx-2 h-0.5 w-16 sm:w-24 ${done ? "bg-brand" : "bg-slate-200"}`} />}
          </div>
        );
      })}
    </div>
  );
}

export function PatientOnboardingPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<FormData>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function update<K extends keyof FormData>(key: K, value: FormData[K]) {
    setForm(f => ({ ...f, [key]: value }));
  }

  async function submit() {
    setBusy(true); setError(null);
    try {
      await createPatientFromOnboarding({
        firstName: form.firstName, lastName: form.lastName,
        dateOfBirth: form.dateOfBirth, gender: form.gender, address: form.address,
        indigenousStatus: form.indigenousStatus, preferredLanguage: form.preferredLanguage,
        contactReason: "Patient onboarding", contactChannel: form.preferredCommunication || "portal",
      });
      navigate("/patients");
    } catch {
      setError("Could not save the patient. Please try again.");
    } finally { setBusy(false); }
  }

  function next() { if (step < 4) setStep(s => s + 1); else submit(); }
  function back() { if (step > 0) setStep(s => s - 1); }

  const stepTitle = ["Patient onboarding", "Patient onboarding", "Patient onboarding", "Patient onboarding", "Patient onboarding"];

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-slate-900">{stepTitle[step]}</h1>
      <p className="mt-1 text-sm text-slate-500">Step {step + 1} of {STEPS.length}</p>
      <div className="mt-6"><Stepper current={step} /></div>

      <div className="mt-6 max-w-4xl rounded-xl border border-slate-200 bg-white p-6">

        {/* Step 1 — Details */}
        {step === 0 && (
          <>
            <h2 className="text-lg font-semibold text-slate-900 mb-5">Personal information</h2>
            <div className="grid grid-cols-2 gap-5">
              <Field label="First Name"><input className={inputClass} value={form.firstName} onChange={e => update("firstName", e.target.value)} /></Field>
              <Field label="Last Name"><input className={inputClass} value={form.lastName} onChange={e => update("lastName", e.target.value)} /></Field>
              <Field label="Date of Birth"><input className={inputClass} placeholder="DD/MM/YYYY" value={form.dateOfBirth} onChange={e => update("dateOfBirth", e.target.value)} /></Field>
              <Field label="Gender"><input className={inputClass} value={form.gender} onChange={e => update("gender", e.target.value)} /></Field>
            </div>
            <div className="mt-5">
              <Field label="MRN"><input className={`${inputClass} bg-slate-50 text-slate-400`} value="MRN-10848 (auto-generated)" disabled /></Field>
            </div>
            <div className="mt-5">
              <Field label="Address"><input className={inputClass} value={form.address} onChange={e => update("address", e.target.value)} /></Field>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-5">
              <Field label="Indigenous Status">
                <select className={inputClass} value={form.indigenousStatus} onChange={e => update("indigenousStatus", e.target.value)}>
                  <option value="">Select...</option>
                  <option>Aboriginal</option><option>Torres Strait Islander</option>
                  <option>Both</option><option>Neither</option><option>Not stated</option>
                </select>
              </Field>
              <Field label="Preferred Language"><input className={inputClass} value={form.preferredLanguage} onChange={e => update("preferredLanguage", e.target.value)} /></Field>
            </div>
          </>
        )}

        {/* Step 2 — Contact */}
        {step === 1 && (
          <>
            <h2 className="text-lg font-semibold text-slate-900 mb-5">Contact details</h2>
            <div className="grid grid-cols-2 gap-5">
              <Field label="Phone"><input className={inputClass} placeholder="+61 4XX XXX XXX" value={form.phone} onChange={e => update("phone", e.target.value)} /></Field>
              <Field label="Email"><input className={inputClass} placeholder="patient@email.com" value={form.email} onChange={e => update("email", e.target.value)} /></Field>
              <Field label="Emergency Contact Name"><input className={inputClass} value={form.emergencyContactName} onChange={e => update("emergencyContactName", e.target.value)} /></Field>
              <Field label="Emergency Contact Phone"><input className={inputClass} value={form.emergencyContactPhone} onChange={e => update("emergencyContactPhone", e.target.value)} /></Field>
              <Field label="Preferred Communication">
                <select className={inputClass} value={form.preferredCommunication} onChange={e => update("preferredCommunication", e.target.value)}>
                  <option value="">Select...</option>
                  <option>Phone</option><option>Email</option><option>SMS</option><option>Portal</option>
                </select>
              </Field>
              <Field label="Best Time to Contact">
                <select className={inputClass} value={form.bestTimeToContact} onChange={e => update("bestTimeToContact", e.target.value)}>
                  <option value="">Select...</option>
                  <option>Morning</option><option>Afternoon</option><option>Evening</option>
                </select>
              </Field>
            </div>
          </>
        )}

        {/* Step 3 — History */}
        {step === 2 && (
          <>
            <h2 className="text-lg font-semibold text-slate-900 mb-5">Medical history</h2>
            <div className="space-y-5">
              <Field label="Known Conditions">
                <textarea className={`${inputClass} h-28 resize-none`} placeholder="Enter conditions, one per line" value={form.knownConditions} onChange={e => update("knownConditions", e.target.value)} />
              </Field>
              <Field label="Current Medications">
                <textarea className={`${inputClass} h-28 resize-none`} placeholder="Enter medications, one per line" value={form.currentMedications} onChange={e => update("currentMedications", e.target.value)} />
              </Field>
              <Field label="Allergies">
                <textarea className={`${inputClass} h-28 resize-none`} placeholder="Enter allergies, one per line" value={form.allergies} onChange={e => update("allergies", e.target.value)} />
              </Field>
            </div>
          </>
        )}

        {/* Step 4 — Insurance */}
        {step === 3 && (
          <>
            <h2 className="text-lg font-semibold text-slate-900 mb-5">Insurance</h2>
            <div className="grid grid-cols-2 gap-5">
              <Field label="Insurance Provider"><input className={inputClass} value={form.insuranceProvider} onChange={e => update("insuranceProvider", e.target.value)} /></Field>
              <Field label="Policy Number"><input className={inputClass} value={form.policyNumber} onChange={e => update("policyNumber", e.target.value)} /></Field>
              <Field label="Group Number"><input className={inputClass} value={form.groupNumber} onChange={e => update("groupNumber", e.target.value)} /></Field>
              <Field label="Expiry Date"><input className={inputClass} placeholder="DD/MM/YYYY" value={form.expiryDate} onChange={e => update("expiryDate", e.target.value)} /></Field>
              <Field label="Medicare Number"><input className={inputClass} value={form.medicareNumber} onChange={e => update("medicareNumber", e.target.value)} /></Field>
              <Field label="Concession Card">
                <select className={inputClass} value={form.concessionCard} onChange={e => update("concessionCard", e.target.value)}>
                  <option>None</option><option>Health Care Card</option><option>Pensioner Concession</option><option>Commonwealth Seniors</option>
                </select>
              </Field>
            </div>
          </>
        )}

        {/* Step 5 — Review */}
        {step === 4 && (
          <>
            <h2 className="text-lg font-semibold text-slate-900 mb-5">Review and submit</h2>
            <div className="rounded-lg border border-slate-200 divide-y divide-slate-100 text-sm">
              {[
                ["NAME", `${form.firstName} ${form.lastName}`.trim() || "—"],
                ["MRN", "MRN-10848 (auto-generated)"],
                ["DOB", form.dateOfBirth || "—"],
                ["GENDER", form.gender || "—"],
                ["ADDRESS", form.address || "—"],
                ["PHONE", form.phone || "—"],
                ["EMAIL", form.email || "—"],
                ["EMERGENCY", form.emergencyContactName || "—"],
                ["CONDITIONS", form.knownConditions || "Not provided"],
                ["MEDICATIONS", form.currentMedications || "Not provided"],
                ["ALLERGIES", form.allergies || "Not provided"],
                ["INSURANCE", [form.insuranceProvider, form.policyNumber].filter(Boolean).join(" ") || "Not provided"],
                ["MEDICARE", form.medicareNumber || "Not provided"],
                ["EXPIRY", form.expiryDate || "Not provided"],
              ].map(([label, value]) => (
                <div key={label} className="flex px-4 py-3">
                  <span className="w-36 shrink-0 font-semibold uppercase tracking-wide text-slate-500 text-xs pt-0.5">{label}:</span>
                  <span className="text-slate-900 whitespace-pre-line">{value}</span>
                </div>
              ))}
            </div>
            <label className="mt-5 flex items-center gap-3 text-sm text-slate-700 cursor-pointer">
              <input type="checkbox" checked={form.confirmed} onChange={e => update("confirmed", e.target.checked)}
                className="h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand" />
              I confirm all details verified with patient
            </label>
            {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
          </>
        )}

        <div className="mt-8 border-t border-slate-100 pt-5 flex items-center justify-between">
          <button onClick={back} disabled={step === 0}
            className="rounded-lg border border-slate-200 px-5 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40">
            Back
          </button>
          <div className="flex gap-3">
            <button className="rounded-lg border border-slate-200 px-5 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50">
              Save draft
            </button>
            <button onClick={next} disabled={busy || (step === 4 && !form.confirmed)}
              className="rounded-lg bg-brand px-6 py-2.5 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50">
              {step === 4 ? (busy ? "Submitting…" : "Submit patient") : "Next"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
