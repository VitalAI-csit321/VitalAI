import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { listPatients } from "../api/cases";
import type { Patient } from "../api/types";
import { StatusBadge, Spinner } from "../components/ui";

export function PatientsPage() {
  const navigate = useNavigate();
  const [patients, setPatients] = useState<Patient[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

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
                  <button onClick={() => navigate(`/consent?patient=${p.id}`)} className="text-brand font-medium hover:underline">View</button>
                  <button onClick={() => navigate("/patients/onboarding")} className="text-brand font-medium hover:underline">Edit</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
