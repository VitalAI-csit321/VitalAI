import { useNavigate, useLocation } from "react-router-dom";
import { Check } from "lucide-react";

interface SuccessState { patientName: string; formType: string; timestamp: string; }

export function ConsentSuccessPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const state = location.state as SuccessState | null;

  const timestamp = state?.timestamp
    ? new Date(state.timestamp).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
    : new Date().toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

  const rows = [
    { label: "Patient", value: state?.patientName ?? "—" },
    { label: "Form", value: state?.formType ?? "—" },
    { label: "Timestamp", value: timestamp },
  ];

  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-emerald-100">
          <Check className="h-8 w-8 text-emerald-600" strokeWidth={2.5} />
        </div>
        <h1 className="mt-5 text-xl font-bold text-slate-900">Consent submitted successfully</h1>
        <p className="mt-1 text-sm text-slate-500">Audit trail</p>

        <div className="mt-6 space-y-3 rounded-xl bg-slate-50 p-5 text-sm">
          {rows.map((r) => (
            <div key={r.label} className="flex justify-between">
              <span className="text-slate-500">{r.label}</span>
              <span className="font-medium text-slate-900">{r.value}</span>
            </div>
          ))}
        </div>

        <div className="mt-6 flex justify-center gap-3">
          <button
            onClick={() => navigate("/records")}
            className="rounded-lg border border-slate-200 px-5 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            View record
          </button>
          <button
            onClick={() => navigate("/consent")}
            className="rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-hover"
          >
            Return to queue
          </button>
        </div>
      </div>
    </div>
  );
}
