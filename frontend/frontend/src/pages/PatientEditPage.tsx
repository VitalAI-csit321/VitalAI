import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getPatient, updatePatient } from "../api/cases";
import type { ProfileFields } from "../api/cases";
import type { Patient } from "../api/types";
import { Spinner } from "../components/ui";
import { PROFILE_FIELD_GROUPS, ProfileFieldInput } from "../components/patientProfileFields";

export function PatientEditPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [patient, setPatient] = useState<Patient | null>(null);
  const [name, setName] = useState("");
  const [dob, setDob] = useState("");
  const [gender, setGender] = useState<Patient["gender"]>("male");
  const [fields, setFields] = useState<ProfileFields>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    getPatient(id).then(p => {
      setPatient(p);
      setName(p.name);
      setDob(p.dob ? new Date(p.dob).toLocaleDateString("en-GB") : "");
      setGender(p.gender);
      setFields({
        address: p.address ?? "", indigenousStatus: p.indigenousStatus ?? "", preferredLanguage: p.preferredLanguage ?? "",
        phone: p.phone ?? "", email: p.email ?? "",
        emergencyContactName: p.emergencyContactName ?? "", emergencyContactPhone: p.emergencyContactPhone ?? "",
        preferredCommunication: p.preferredCommunication ?? "", bestTimeToContact: p.bestTimeToContact ?? "",
        knownConditions: p.knownConditions ?? "", currentMedications: p.currentMedications ?? "", allergies: p.allergies ?? "",
        insuranceProvider: p.insuranceProvider ?? "", policyNumber: p.policyNumber ?? "", groupNumber: p.groupNumber ?? "",
        expiryDate: p.expiryDate ? new Date(p.expiryDate).toLocaleDateString("en-GB") : "",
        medicareNumber: p.medicareNumber ?? "", concessionCard: p.concessionCard ?? "",
      });
    }).catch(() => setError("Could not load this patient.")).finally(() => setLoading(false));
  }, [id]);

  function setField(key: keyof ProfileFields, value: string) {
    setFields(f => ({ ...f, [key]: value }));
  }

  async function save() {
    if (!id) return;
    setBusy(true); setError(null);
    try {
      await updatePatient(id, { name, dob, gender, ...fields });
      navigate(`/patients/${id}`);
    } catch {
      setError("Could not save changes. Please try again.");
      setBusy(false);
    }
  }

  async function setStatus(status: string) {
    if (!id) return;
    setBusy(true); setError(null);
    try {
      await updatePatient(id, { status });
      navigate(`/patients/${id}`);
    } catch {
      setError("Could not update status. Please try again.");
      setBusy(false);
    }
  }

  if (loading) return <div className="p-6"><Spinner label="Loading patient..." /></div>;
  if (!patient) return (
    <div className="p-6">
      <p className="text-sm text-red-600">{error ?? "Patient not found."}</p>
      <button onClick={() => navigate("/patients")} className="mt-4 text-sm text-brand hover:underline">Back to patients</button>
    </div>
  );

  return (
    <div className="p-6">
      <button onClick={() => navigate(`/patients/${id}`)} className="text-sm text-slate-500 hover:text-slate-700">← Back to patient</button>
      <h1 className="mt-4 text-2xl font-bold text-slate-900">Edit patient</h1>

      <div className="mt-6 max-w-4xl rounded-xl border border-slate-200 bg-white p-6 space-y-8">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 mb-5">Identity</h2>
          <div className="grid grid-cols-2 gap-5">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">Name</label>
              <input className="w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm outline-none focus:border-brand focus:ring-1 focus:ring-brand" value={name} onChange={e => setName(e.target.value)} />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">Date of birth</label>
              <input placeholder="DD/MM/YYYY" className="w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm outline-none focus:border-brand focus:ring-1 focus:ring-brand" value={dob} onChange={e => setDob(e.target.value)} />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">Gender</label>
              <select className="w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm outline-none focus:border-brand focus:ring-1 focus:ring-brand" value={gender} onChange={e => setGender(e.target.value as Patient["gender"])}>
                <option value="male">Male</option><option value="female">Female</option><option value="non_binary">Non-binary</option>
              </select>
            </div>
          </div>
        </div>

        {PROFILE_FIELD_GROUPS.map(group => (
          <div key={group.title}>
            <h2 className="text-lg font-semibold text-slate-900 mb-5">{group.title}</h2>
            <div className="grid grid-cols-2 gap-5">
              {group.fields.map(def => (
                <ProfileFieldInput key={def.key} def={def} value={fields[def.key] ?? ""} onChange={v => setField(def.key, v)} />
              ))}
            </div>
          </div>
        ))}

        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>

      <div className="mt-6 max-w-4xl flex items-center justify-between">
        {patient.status === "inactive" ? (
          <button
            onClick={() => setStatus(patient.missingFields.length === 0 ? "active" : "pending")}
            disabled={busy}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Reactivate
          </button>
        ) : (
          <button
            onClick={() => setStatus("inactive")}
            disabled={busy}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Mark inactive
          </button>
        )}
        <button onClick={save} disabled={busy} className="rounded-lg bg-brand px-6 py-2.5 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50">
          {busy ? "Saving…" : "Save changes"}
        </button>
      </div>
    </div>
  );
}
