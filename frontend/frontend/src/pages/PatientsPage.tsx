import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { listPatients, updatePatient } from "../api/cases";
import type { Patient } from "../api/types";
import { StatusBadge, Spinner } from "../components/ui";

function PatientEditModal({ patient, onClose, onSaved }: { patient: Patient; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(patient.name);
  const [dob, setDob] = useState(patient.dob ? new Date(patient.dob).toLocaleDateString("en-GB") : "");
  const [gender, setGender] = useState(patient.gender);
  const [status, setStatus] = useState(patient.status);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true); setError(null);
    try {
      await updatePatient(patient.id, { name, dob, gender, status });
      onSaved();
      onClose();
    } catch {
      setError("Could not save changes. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-bold text-slate-900">Edit patient</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xl">×</button>
        </div>
        <div className="space-y-4 text-sm">
          <div><label className="block font-medium text-slate-700 mb-1.5">Name</label><input value={name} onChange={e=>setName(e.target.value)} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 outline-none focus:border-brand" /></div>
          <div><label className="block font-medium text-slate-700 mb-1.5">Date of birth</label><input placeholder="DD/MM/YYYY" value={dob} onChange={e=>setDob(e.target.value)} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 outline-none focus:border-brand" /></div>
          <div><label className="block font-medium text-slate-700 mb-1.5">Gender</label>
            <select value={gender} onChange={e=>setGender(e.target.value as Patient["gender"])} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 outline-none focus:border-brand">
              <option value="male">Male</option><option value="female">Female</option><option value="non_binary">Non-binary</option>
            </select>
          </div>
          <div><label className="block font-medium text-slate-700 mb-1.5">Status</label>
            <select value={status} onChange={e=>setStatus(e.target.value as Patient["status"])} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 outline-none focus:border-brand">
              <option value="active">Active</option><option value="pending">Pending</option><option value="inactive">Inactive</option>
            </select>
          </div>
          {error && <p className="text-red-600">{error}</p>}
        </div>
        <div className="mt-5 flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-lg border border-slate-200 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
          <button onClick={save} disabled={busy} className="flex-1 rounded-lg bg-brand py-2.5 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50">{busy?"Saving…":"Save changes"}</button>
        </div>
      </div>
    </div>
  );
}

export function PatientsPage() {
  const navigate = useNavigate();
  const [patients, setPatients] = useState<Patient[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [editingPatient, setEditingPatient] = useState<Patient | null>(null);

  useEffect(() => {
    setLoading(true);
    const t = setTimeout(() => {
      listPatients({ search, limit: 25 })
        .then(res => { setPatients(res.items); setTotal(res.total); })
        .catch(() => {})
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Patients</h1>
          <p className="mt-1 text-sm text-slate-500">{total} total</p>
        </div>
        <button onClick={() => navigate("/patients/onboarding")} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover">New patient</button>
      </div>

      <div className="mt-6 relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search patients..."
          className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm outline-none focus:border-brand" />
      </div>

      <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              {["MRN","Name","DOB","Gender","Status","Actions"].map(h => <th key={h} className="px-6 py-3">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {loading ? <tr><td colSpan={6} className="px-6 py-8 text-center"><Spinner /></td></tr>
            : patients.length === 0 ? <tr><td colSpan={6} className="px-6 py-8 text-sm text-slate-500">No patients found.</td></tr>
            : patients.map(p => (
              <tr key={p.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                <td className="px-6 py-4 font-mono text-sm text-slate-700">{p.mrn}</td>
                <td className="px-6 py-4 font-medium text-slate-900">{p.name}</td>
                <td className="px-6 py-4 text-slate-600">{p.dob ? new Date(p.dob).toLocaleDateString("en-GB") : "—"}</td>
                <td className="px-6 py-4 text-slate-600 capitalize">{p.gender?.replace("_"," ") ?? "—"}</td>
                <td className="px-6 py-4">
                  <StatusBadge tone={p.status === "active" ? "green" : p.status === "pending" ? "amber" : "gray"}>{p.status}</StatusBadge>
                </td>
                <td className="px-6 py-4 flex gap-4">
                  <button onClick={() => navigate(`/patients/${p.id}`)} className="text-brand font-medium hover:underline">View</button>
                  <button onClick={() => setEditingPatient(p)} className="text-brand font-medium hover:underline">Edit</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editingPatient && <PatientEditModal patient={editingPatient} onClose={() => setEditingPatient(null)} onSaved={() => listPatients({ search, limit: 25 }).then(res => { setPatients(res.items); setTotal(res.total); })} />}
    </div>
  );
}
