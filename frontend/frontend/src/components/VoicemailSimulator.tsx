import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { simulateVoicemail } from "../api/calls";

const MAX_AUDIO_BYTES = 25 * 1024 * 1024;

const INTENTS = [
  { digit: "", label: "No key pressed" },
  { digit: "1", label: "1 - Appointments" },
  { digit: "2", label: "2 - Results" },
  { digit: "3", label: "3 - Prescriptions" },
  { digit: "4", label: "4 - Anything else" },
];

export function VoicemailSimulator() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [fromNumber, setFromNumber] = useState("");
  const [dobDigits, setDobDigits] = useState("");
  const [intentDigit, setIntentDigit] = useState("");
  const [urgent, setUrgent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queued, setQueued] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return setError("Choose an audio file.");
    if (file.size > MAX_AUDIO_BYTES) return setError("Audio file is too large (max 25MB).");
    if (!fromNumber.trim()) return setError("Enter the caller's number, or 'anonymous'.");
    if (dobDigits && !/^\d{8}$/.test(dobDigits)) return setError("Date of birth must be 8 digits, DDMMYYYY.");
    setBusy(true);
    setError(null);
    try {
      await simulateVoicemail({ file, fromNumber: fromNumber.trim(), dobDigits, intentDigit, urgent });
      setQueued(true);
    } catch {
      setError("Could not submit this voicemail. Check the fields and try again.");
    } finally {
      setBusy(false);
    }
  }

  if (queued) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 text-center">
        <h2 className="text-xl font-bold text-slate-900">Voicemail received</h2>
        <p className="mt-2 text-sm text-slate-600">
          It is being transcribed and classified. The callback task appears in the inbox in a minute or two.
        </p>
        <div className="mt-6 flex justify-center gap-3">
          <button
            onClick={() => { setQueued(false); setFile(null); }}
            className="rounded-lg border border-slate-200 px-5 py-2 text-sm font-medium text-slate-700"
          >
            Simulate another
          </button>
          <button onClick={() => navigate("/inbox")} className="rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white">
            View in inbox
          </button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="max-w-xl space-y-4 rounded-xl border border-slate-200 bg-white p-6">
      <p className="text-sm text-slate-500">
        Stands in for a Twilio call: the same keypad answers and recording a real caller would leave.
      </p>
      <label className="block text-sm">
        <span className="font-semibold text-slate-700">Recording</span>
        <input type="file" accept=".wav,.mp3,.m4a,.ogg,.webm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="mt-1 block w-full text-sm" />
      </label>
      <label className="block text-sm">
        <span className="font-semibold text-slate-700">Caller ID</span>
        <input value={fromNumber} onChange={(e) => setFromNumber(e.target.value)} placeholder="+61412345678 or anonymous" className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2" />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={urgent} onChange={(e) => setUrgent(e.target.checked)} />
        <span className="font-semibold text-slate-700">Pressed 9 (urgent)</span>
      </label>
      <label className="block text-sm">
        <span className="font-semibold text-slate-700">Keypad date of birth (DDMMYYYY)</span>
        <input value={dobDigits} onChange={(e) => setDobDigits(e.target.value)} inputMode="numeric" maxLength={8} className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2" />
      </label>
      <label className="block text-sm">
        <span className="font-semibold text-slate-700">Menu choice</span>
        <select value={intentDigit} onChange={(e) => setIntentDigit(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2">
          {INTENTS.map((i) => <option key={i.digit} value={i.digit}>{i.label}</option>)}
        </select>
      </label>
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      <button type="submit" disabled={busy} className="rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white disabled:opacity-60">
        {busy ? "Submitting..." : "Submit voicemail"}
      </button>
    </form>
  );
}
