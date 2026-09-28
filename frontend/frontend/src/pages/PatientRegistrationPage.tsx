import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import {
  getRegistrationLink,
  submitRegistration,
  type RegistrationForm,
  type RegistrationLink,
} from "../api/registration";
import { SignaturePad } from "../components/SignaturePad";
import { ApiError, describeApiError } from "../lib/apiClient";

// text-base, not text-sm: iOS zooms into inputs under 16px.
const input =
  "w-full rounded-lg border border-slate-300 bg-white px-3.5 py-2.5 text-base outline-none focus:border-brand focus:ring-1 focus:ring-brand";

const EMPTY: RegistrationForm = {
  name: "", dob: "", phone: "", gender: "", address: "",
  emergency_contact_name: "", emergency_contact_phone: "", preferred_language: "",
  preferred_communication: "", preferred_day: "", part_of_day: "any",
};

function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
      <h2 className="mb-4 text-base font-semibold text-slate-900">{title}</h2>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

function Field({ label, optional, children }: { label: string; optional?: boolean; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-slate-700">
        {label}
        {optional && <span className="font-normal text-slate-400"> (optional)</span>}
      </span>
      {children}
    </label>
  );
}

export function PatientRegistrationPage() {
  const { token = "" } = useParams<{ token: string }>();
  const [link, setLink] = useState<RegistrationLink | null>(null);
  const [state, setState] = useState<"loading" | "invalid" | "form" | "done">("loading");
  const [form, setForm] = useState<RegistrationForm>(EMPTY);
  const [signed, setSigned] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    getRegistrationLink(token)
      .then((l) => { setLink(l); setState("form"); })
      .catch(() => setState("invalid"));
  }, [token]);

  function update<K extends keyof RegistrationForm>(key: K, value: RegistrationForm[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!signed) { setError("Please sign in the box before sending the form."); return; }
    setError(null);
    setBusy(true);
    try {
      await submitRegistration(token, {
        ...form,
        agree_data: true,
        agree_contact: true,
        signature: canvasRef.current?.toDataURL("image/png") ?? "",
      });
      setState("done");
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setState("invalid");
      else if (err instanceof ApiError && err.status === 429) setError("Too many attempts. Please wait a minute and try again.");
      else setError(describeApiError(err, "Could not send the form. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  const today = new Date();
  const lastDay = new Date(today.getTime() + 60 * 24 * 3600 * 1000);

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-8">
      <div className="mx-auto w-full max-w-xl">
        <h1 className="text-xl font-bold text-slate-900">Register with the clinic</h1>

        {state === "loading" && <p className="mt-6 text-sm text-slate-500">Loading…</p>}

        {state === "invalid" && (
          <div className="mt-6 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
            This link is not valid. It may have expired or already been used. Please contact the clinic.
          </div>
        )}

        {state === "done" && (
          <div className="mt-6 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            Thank you. Your details have been sent. We will email you your reference number
            {link?.needsPreferredDay ? " and the times available" : ""} shortly.
          </div>
        )}

        {state === "form" && link && (
          <form onSubmit={onSubmit} className="mt-6 space-y-5">
            <Section title="About you">
              <Field label="Full name">
                <input className={input} value={form.name} onChange={(e) => update("name", e.target.value)} autoComplete="name" maxLength={255} required />
              </Field>
              <Field label="Date of birth">
                <input className={input} type="date" value={form.dob} max={isoDate(new Date(today.getTime() - 24 * 3600 * 1000))} onChange={(e) => update("dob", e.target.value)} autoComplete="bday" required />
              </Field>
              <Field label="Gender" optional>
                <select className={input} value={form.gender} onChange={(e) => update("gender", e.target.value)}>
                  <option value="">Prefer not to say</option>
                  <option value="male">Male</option>
                  <option value="female">Female</option>
                  <option value="non_binary">Non-binary</option>
                </select>
              </Field>
            </Section>

            <Section title="Contact">
              <Field label="Email">
                <input className={`${input} bg-slate-100 text-slate-500`} value={link.email} disabled />
              </Field>
              <Field label="Phone">
                <input className={input} type="tel" value={form.phone} onChange={(e) => update("phone", e.target.value)} autoComplete="tel" pattern="[0-9 +()\-]{6,32}" required />
              </Field>
              <Field label="Address" optional>
                <input className={input} value={form.address} onChange={(e) => update("address", e.target.value)} autoComplete="street-address" maxLength={255} />
              </Field>
              <Field label="Emergency contact name" optional>
                <input className={input} value={form.emergency_contact_name} onChange={(e) => update("emergency_contact_name", e.target.value)} maxLength={255} />
              </Field>
              <Field label="Emergency contact phone" optional>
                <input className={input} type="tel" value={form.emergency_contact_phone} onChange={(e) => update("emergency_contact_phone", e.target.value)} maxLength={255} />
              </Field>
              <Field label="Preferred language" optional>
                <input className={input} value={form.preferred_language} onChange={(e) => update("preferred_language", e.target.value)} maxLength={255} />
              </Field>
              <Field label="Preferred way to contact you" optional>
                <select className={input} value={form.preferred_communication} onChange={(e) => update("preferred_communication", e.target.value)}>
                  <option value="">No preference</option>
                  <option>Phone</option><option>Email</option><option>SMS</option>
                </select>
              </Field>
            </Section>

            <Section title="Appointment">
              <Field label="Preferred day" optional={!link.needsPreferredDay}>
                <input className={input} type="date" value={form.preferred_day} min={isoDate(today)} max={isoDate(lastDay)} onChange={(e) => update("preferred_day", e.target.value)} required={link.needsPreferredDay} />
              </Field>
              <Field label="Time of day">
                <select className={input} value={form.part_of_day} onChange={(e) => update("part_of_day", e.target.value as RegistrationForm["part_of_day"])}>
                  <option value="any">Any time</option>
                  <option value="morning">Morning</option>
                  <option value="afternoon">Afternoon</option>
                </select>
              </Field>
            </Section>

            <Section title="Consent">
              {link.statements.map((statement) => (
                <label key={statement} className="flex items-start gap-3 text-sm text-slate-700">
                  <input type="checkbox" required className="mt-0.5 h-5 w-5 shrink-0 rounded border-slate-300 text-brand" />
                  {statement}
                </label>
              ))}
              <div>
                <span className="mb-1.5 block text-sm font-medium text-slate-700">Signature</span>
                <SignaturePad onChange={setSigned} canvasRef={canvasRef} />
                <p className="mt-1.5 text-xs text-slate-500">Sign with your finger or mouse.</p>
              </div>
            </Section>

            {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
            <button type="submit" disabled={busy} className="w-full rounded-lg bg-brand py-3 text-base font-semibold text-white hover:bg-brand-hover disabled:opacity-60">
              {busy ? "Sending…" : "Send"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
