import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

export function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);

  // No password-reset endpoint exists on the backend yet. The form shows the
  // approved confirmation state; wire it to a real reset endpoint when one is
  // added — this component's markup stays the same.
  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSent(true);
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-sidebar px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-xl">
        <button
          onClick={() => navigate(-1)}
          className="mb-6 flex items-center gap-2 text-sm font-medium text-slate-700 hover:text-slate-900"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </button>

        <h1 className="text-xl font-bold text-slate-900">VitalAI</h1>
        <h2 className="mt-1 text-lg font-semibold text-slate-800">Reset your password</h2>
        <p className="mt-2 text-sm text-slate-500">
          Enter your email address and we'll send you a link to reset your password.
        </p>

        {sent ? (
          <div className="mt-6 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            If an account exists for {email}, a reset link is on its way.
          </div>
        ) : (
          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            <div>
              <label className="mb-1.5 block text-sm font-semibold text-slate-700">
                Email address
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Enter your email"
                className="w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm outline-none focus:border-brand focus:ring-1 focus:ring-brand"
                required
              />
            </div>
            <button
              type="submit"
              className="w-full rounded-lg bg-brand py-2.5 text-sm font-semibold text-white hover:bg-brand-hover"
            >
              Send reset link
            </button>
          </form>
        )}

        <div className="mt-6 text-center">
          <Link to="/login" className="text-sm font-medium text-brand hover:underline">
            Back to sign in
          </Link>
        </div>
      </div>
    </div>
  );
}
