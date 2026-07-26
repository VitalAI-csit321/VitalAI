import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiPost } from "../lib/apiClient";

interface IngestResult {
  category: string;
  confidence: number;
  target_role: string;
  outcome: "auto_routed" | "auto_routed_flagged" | "human_review";
  override_reason: string | null;
  draft_text: string | null;
  sent: boolean;
  blocked: boolean;
}

function formatLabel(value: string): string {
  return value
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function ComposePage() {
  const navigate = useNavigate();
  const [sender, setSender] = useState("");
  const [recipient, setRecipient] = useState("clinic@example.com");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IngestResult | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await apiPost<IngestResult>("/api/v1/email/ingest", {
        sender,
        recipient,
        subject,
        body,
      });
      setResult(res);
    } catch {
      setError("Could not process this email. Check the fields and try again.");
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    return (
      <div className="flex items-center justify-center min-h-full p-6">
        <div className="w-full max-w-lg rounded-xl border border-slate-200 bg-white p-6 text-center">
          <div className="text-5xl mb-4">✓</div>
          <h2 className="text-xl font-bold text-slate-900">Email processed</h2>
          <p className="mt-2 text-sm text-slate-500">
            The classifier and routing gate ran on this message in real time.
          </p>

          <div className="mt-5 space-y-2 rounded-lg bg-slate-50 p-4 text-left text-sm">
            <div>
              <span className="font-semibold text-slate-700">Category: </span>
              {formatLabel(result.category)} ({Math.round(result.confidence * 100)}% confidence)
            </div>
            <div>
              <span className="font-semibold text-slate-700">Routed to: </span>
              {formatLabel(result.target_role)}
            </div>
            <div>
              <span className="font-semibold text-slate-700">Outcome: </span>
              {formatLabel(result.outcome)}
              {result.override_reason && ` (${formatLabel(result.override_reason)})`}
            </div>
            {result.blocked && (
              <div className="font-medium text-red-600">
                Draft reply blocked by the output guardrail, routed to a human instead.
              </div>
            )}
            {result.draft_text && (
              <div>
                <span className="font-semibold text-slate-700">
                  Draft reply {result.sent ? "(sent automatically)" : "(awaiting approval)"}:
                </span>
                <p className="mt-1 whitespace-pre-line text-slate-600">{result.draft_text}</p>
              </div>
            )}
            {!result.draft_text && !result.blocked && (
              <div className="text-slate-500">
                No draft generated. This went straight to human review.
              </div>
            )}
          </div>

          <div className="mt-6 flex justify-center gap-3">
            <button
              onClick={() => setResult(null)}
              className="rounded-lg border border-slate-200 px-5 py-2 text-sm font-medium text-slate-700"
            >
              Simulate another
            </button>
            <button
              onClick={() => navigate("/inbox")}
              className="rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white"
            >
              View in inbox
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-slate-900 mb-1">Simulate incoming email</h1>
      <p className="text-sm text-slate-500 mb-6">
        This runs the real pipeline end to end: classification, RBAC routing, draft generation,
        and the output guardrail. There's no live email account behind this; it's how new patient
        email gets into the system in this MVP.
      </p>
      <form onSubmit={onSubmit} className="max-w-xl rounded-xl border border-slate-200 bg-white p-5 space-y-4">
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">From (patient email)</label>
          <input
            required
            type="email"
            value={sender}
            onChange={(e) => setSender(e.target.value)}
            placeholder="patient@example.com"
            className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand"
          />
        </div>
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">To</label>
          <input
            required
            type="email"
            value={recipient}
            onChange={(e) => setRecipient(e.target.value)}
            className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand"
          />
        </div>
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">Subject</label>
          <input
            required
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand"
          />
        </div>
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">Message</label>
          <textarea
            required
            value={body}
            onChange={(e) => setBody(e.target.value)}
            className="w-full rounded-lg border border-slate-200 px-3.5 py-3 text-sm outline-none focus:border-brand resize-none h-40 leading-relaxed"
          />
        </div>
        {error && <p className="text-sm font-medium text-red-600">{error}</p>}
        <div className="flex justify-end gap-3 pt-1">
          <button
            type="button"
            onClick={() => navigate("/inbox")}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50"
          >
            {busy ? "Processing…" : "Send through pipeline"}
          </button>
        </div>
      </form>
    </div>
  );
}
