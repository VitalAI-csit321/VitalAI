import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { transcribeAudio, createCall, routeCall } from "../api/calls";
import type { CallRouteResult } from "../api/calls";
import { listCases } from "../api/cases";
import type { Case } from "../api/types";

const MAX_AUDIO_BYTES = 25 * 1024 * 1024;

function formatLabel(value: string): string {
  return value
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function LogCallPage() {
  const navigate = useNavigate();
  const [cases, setCases] = useState<Case[]>([]);
  const [caseId, setCaseId] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [transcript, setTranscript] = useState("");
  const [transcribing, setTranscribing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CallRouteResult | null>(null);

  useEffect(() => {
    listCases({ limit: 100 }).then((r) => setCases(r.items)).catch(() => {});
  }, []);

  async function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0] ?? null;
    setError(null);
    setFile(selected);
    if (!selected) return;
    if (selected.size > MAX_AUDIO_BYTES) {
      setError("Audio file is too large (max 25MB).");
      setFile(null);
      return;
    }
    setTranscribing(true);
    try {
      const text = await transcribeAudio(selected);
      setTranscript(text);
    } catch {
      setError("Could not transcribe this audio. Try a different file.");
    } finally {
      setTranscribing(false);
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!transcript.trim()) {
      setError("A transcript is required before routing.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const call = await createCall(caseId, phoneNumber, transcript);
      const routed = await routeCall(call.id);
      setResult(routed);
    } catch {
      setError("Could not log this call. Check the fields and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (result) {
    return (
      <div className="flex items-center justify-center min-h-full p-6">
        <div className="w-full max-w-lg rounded-xl border border-slate-200 bg-white p-6 text-center">
          <div className="text-5xl mb-4">✓</div>
          <h2 className="text-xl font-bold text-slate-900">Call logged</h2>
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
          </div>
          <div className="mt-6 flex justify-center gap-3">
            <button
              onClick={() => {
                setResult(null);
                setFile(null);
                setTranscript("");
              }}
              className="rounded-lg border border-slate-200 px-5 py-2 text-sm font-medium text-slate-700"
            >
              Log another
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
      <h1 className="text-2xl font-bold text-slate-900 mb-1">Log a call</h1>
      <p className="text-sm text-slate-500 mb-6">
        Upload a recorded call. It's transcribed locally, then you review the transcript before
        it runs through the real classification and routing pipeline. No live phone line yet —
        this is how a call gets into the system in this MVP.
      </p>
      <form onSubmit={onSubmit} className="max-w-xl rounded-xl border border-slate-200 bg-white p-5 space-y-4">
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">Case</label>
          <select
            required
            value={caseId}
            onChange={(e) => setCaseId(e.target.value)}
            className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand"
          >
            <option value="" disabled>Select a case</option>
            {cases.map((c) => (
              <option key={c.id} value={c.id}>{c.patientName} — {c.contactReason}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">Caller phone number</label>
          <input
            required
            value={phoneNumber}
            onChange={(e) => setPhoneNumber(e.target.value)}
            placeholder="0412345678"
            className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand"
          />
        </div>
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">Call recording</label>
          <input
            required
            type="file"
            accept="audio/*"
            onChange={onFileChange}
            className="w-full text-sm"
          />
          {transcribing && <p className="mt-1.5 text-sm text-slate-500">Transcribing…</p>}
        </div>
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1.5">Transcript (review before submitting)</label>
          <textarea
            required
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
            className="w-full rounded-lg border border-slate-200 px-3.5 py-3 text-sm outline-none focus:border-brand resize-none h-40 leading-relaxed"
            placeholder="Transcript will appear here after upload — edit if the transcription got anything wrong."
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
            disabled={submitting || transcribing || !file}
            className="rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50"
          >
            {submitting ? "Logging…" : "Log and route call"}
          </button>
        </div>
      </form>
    </div>
  );
}
