import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search, SlidersHorizontal } from "lucide-react";
import { listPatients } from "../api/cases";
import type { Patient, PatientStatus } from "../api/types";
import { StatusBadge, Spinner } from "../components/ui";

const STATUS_TONE: Record<PatientStatus, "green" | "amber" | "gray"> = {
  active: "green",
  pending: "amber",
  inactive: "gray",
};

export function PatientsPage() {
  const navigate = useNavigate();
  const [patients, setPatients] = useState<Patient[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    const t = setTimeout(() => {
      listPatients({ search, limit: 25 })
        .then((page) => {
          setPatients(page.items);
          setTotal(page.total);
          setError(null);
        })
        .catch(() => setError("Could not load patients."))
        .finally(() => setLoading(false));
    }, 200);
    return () => clearTimeout(t);
  }, [search]);

  const active = patients.filter((p) => p.status === "active").length;
  const pending = patients.filter((p) => p.status === "pending").length;

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Patients</h1>
          <p className="mt-1 text-sm text-slate-500">
            {total ? `${total} total` : `${active} active`} • {pending} pending
          </p>
        </div>
        <button
          onClick={() => navigate("/patients/onboarding")}
          className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover"
        >
          New patient
        </button>
      </div>

      <div className="mt-6 flex gap-3">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search patients..."
            className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm outline-none focus:border-brand"
          />
        </div>
        <button className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50">
          <SlidersHorizontal className="h-4 w-4" />
          Filters
        </button>
      </div>

      <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <th className="px-6 py-3">MRN</th>
              <th className="px-6 py-3">Name</th>
              <th className="px-6 py-3">Date of Birth</th>
              <th className="px-6 py-3">Gender</th>
              <th className="px-6 py-3">Status</th>
              <th className="px-6 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className="px-6 py-8">
                  <Spinner />
                </td>
              </tr>
            ) : error ? (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-sm text-red-600">
                  {error}
                </td>
              </tr>
            ) : patients.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-sm text-slate-500">
                  No patients found.
                </td>
              </tr>
            ) : (
              patients.map((p) => (
                <tr key={p.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                  <td className="px-6 py-4 font-medium text-slate-900">{p.mrn}</td>
                  <td className="px-6 py-4 text-slate-700">{p.name}</td>
                  <td className="px-6 py-4 text-slate-600">{(p.dob ? new Date(p.dob).toLocaleDateString("en-GB") : "—")}</td>
                  <td className="px-6 py-4 text-slate-600">{(p.gender ? p.gender.charAt(0).toUpperCase()+p.gender.slice(1).replace("_"," ") : "—")}</td>
                  <td className="px-6 py-4">
                    <StatusBadge tone={STATUS_TONE[p.status]}>{p.status}</StatusBadge>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex gap-4">
                      <button className="font-medium text-brand hover:underline">View</button>
                      <button className="font-medium text-brand hover:underline">Edit</button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
