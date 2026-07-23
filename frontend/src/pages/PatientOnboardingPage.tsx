import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createPatientFromOnboarding } from "../api/cases";

const STEPS = ["Details", "Contact", "History", "Insurance", "Review"];

interface FormData {
  firstName: string;
  lastName: string;
  dateOfBirth: string;
  gender: string;
  address: string;
  indigenousStatus: string;
  preferredLanguage: string;
}

const EMPTY: FormData = {
  firstName: "",
  lastName: "",
  dateOfBirth: "",
  gender: "",
  address: "",
  indigenousStatus: "",
  preferredLanguage: "",
};

function Stepper({ current }: { current: number }) {
  return (
    <div className="flex items-center">
      {STEPS.map((label, i) => {
        const active = i === current;
        const done = i < current;
        return (
          <div key={label} className="flex items-center">
            <div className="flex flex-col items-center">
              <div
                className={`flex h-9 w-9 items-center justify-center rounded-full border-2 text-sm font-semibold ${
                  active
                    ? "border-brand text-brand"
                    : done
                      ? "border-brand bg-brand text-white"
                      : "border-slate-300 text-slate-400"
                }`}
              >
                {i + 1}
              </div>
              <span
                className={`mt-1.5 text-xs ${active ? "font-semibold text-slate-800" : "text-slate-400"}`}
              >
                {label}
              </span>
            </div>
            {i < STEPS.length - 1 && <div className="mx-2 h-px w-16 bg-slate-200 sm:w-24" />}
          </div>
        );
      })}
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-sm font-semibold text-slate-700">{label}</label>
      {children}
    </div>
  );
}

const inputClass =
  "w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm outline-none focus:border-brand focus:ring-1 focus:ring-brand";

export function PatientOnboardingPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<FormData>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function update<K extends keyof FormData>(key: K, value: FormData[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function finish() {
    setBusy(true);
    setError(null);
    try {
      await createPatientFromOnboarding(form);
      navigate("/patients");
    } catch {
      setError("Could not save the patient. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  function next() {
    if (step < STEPS.length - 1) setStep(step + 1);
    else finish();
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-slate-900">Patient onboarding</h1>
      <p className="mt-1 text-sm text-slate-500">
        Step {step + 1} of {STEPS.length}
      </p>

      <div className="mt-6">
        <Stepper current={step} />
      </div>

      <div className="mt-6 max-w-3xl rounded-xl border border-slate-200 bg-white p-6">
        {step === 0 && (
          <>
            <h2 className="text-base font-semibold text-slate-900">Personal information</h2>
            <div className="mt-5 grid grid-cols-1 gap-5 sm:grid-cols-2">
              <Field label="First Name">
                <input
                  className={inputClass}
                  value={form.firstName}
                  onChange={(e) => update("firstName", e.target.value)}
                />
              </Field>
              <Field label="Last Name">
                <input
                  className={inputClass}
                  value={form.lastName}
                  onChange={(e) => update("lastName", e.target.value)}
                />
              </Field>
              <Field label="Date of Birth">
                <input
                  className={inputClass}
                  placeholder="DD/MM/YYYY"
                  value={form.dateOfBirth}
                  onChange={(e) => update("dateOfBirth", e.target.value)}
                />
              </Field>
              <Field label="Gender">
                <input
                  className={inputClass}
                  value={form.gender}
                  onChange={(e) => update("gender", e.target.value)}
                />
              </Field>
            </div>

            <div className="mt-5">
              <Field label="MRN">
                <input
                  className={`${inputClass} bg-slate-50 text-slate-400`}
                  value="MRN-10848 (auto-generated)"
                  disabled
                />
              </Field>
            </div>

            <div className="mt-5">
              <Field label="Address">
                <input
                  className={inputClass}
                  value={form.address}
                  onChange={(e) => update("address", e.target.value)}
                />
              </Field>
            </div>

            <div className="mt-5 grid grid-cols-1 gap-5 sm:grid-cols-2">
              <Field label="Indigenous Status">
                <select
                  className={inputClass}
                  value={form.indigenousStatus}
                  onChange={(e) => update("indigenousStatus", e.target.value)}
                >
                  <option value="">Select...</option>
                  <option>Aboriginal</option>
                  <option>Torres Strait Islander</option>
                  <option>Both</option>
                  <option>Neither</option>
                  <option>Not stated</option>
                </select>
              </Field>
              <Field label="Preferred Language">
                <input
                  className={inputClass}
                  value={form.preferredLanguage}
                  onChange={(e) => update("preferredLanguage", e.target.value)}
                />
              </Field>
            </div>
          </>
        )}

        {step > 0 && (
          <div className="py-8 text-center text-sm text-slate-500">
            The “{STEPS[step]}” step design hasn't been provided yet. Continue to save the details
            captured in step 1.
          </div>
        )}

        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

        <div className="mt-8 border-t border-slate-100 pt-5">
          <div className="flex items-center justify-between">
            <button
              onClick={() => setStep(Math.max(0, step - 1))}
              disabled={step === 0}
              className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40"
            >
              Back
            </button>
            <div className="flex gap-3">
              <button className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
                Save draft
              </button>
              <button
                onClick={next}
                disabled={busy}
                className="rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-60"
              >
                {step === STEPS.length - 1 ? (busy ? "Saving…" : "Finish") : "Next"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
