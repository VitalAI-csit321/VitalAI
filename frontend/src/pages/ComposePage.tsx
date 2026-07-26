import { useState } from "react";
import { Paperclip } from "lucide-react";

const AI_SUGGESTION = {
  subject: "Williams discharge documentation - cleared for tomorrow",
  body: `Hi Catherine and Lisa,

I've completed my review of the Williams discharge documentation and everything is in order. We're clear to proceed with the planned discharge tomorrow morning.

All required signatures have been obtained and the care plan has been shared with the patient's family.

Best regards,
Sanjay`,
};

const TONES = ["Concise", "Formal", "Friendly", "Detailed"];

export function ComposePage() {
  const [to, setTo] = useState(["DR C HINES", "DR L LIM"]);
  const [toInput, setToInput] = useState("");
  const [cc, setCc] = useState("");
  const [subject, setSubject] = useState("Williams discharge cleared");
  const [message, setMessage] = useState(`Hi Catherine and Lisa,

I've completed the review of the Williams discharge documentation. Everything looks good and we're clear to proceed with the discharge as planned tomorrow morning.

All required signatures are in place and the care plan has been shared with the family.

Best regards,
Sanjay`);
  const [tone, setTone] = useState("Concise");
  const [sent, setSent] = useState(false);

  if (sent) {
    return (
      <div className="flex items-center justify-center min-h-full p-6">
        <div className="text-center">
          <div className="text-5xl mb-4">✓</div>
          <h2 className="text-xl font-bold text-slate-900">Message sent</h2>
          <p className="mt-2 text-sm text-slate-500">Your message has been delivered to all recipients.</p>
          <button onClick={() => setSent(false)} className="mt-6 rounded-lg bg-brand px-6 py-2 text-sm font-semibold text-white">Compose another</button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-slate-900 mb-6">Compose message</h1>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.3fr_1fr]">
        <div className="rounded-xl border border-slate-200 bg-white p-5 space-y-4">
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1.5">To</label>
            <div className="flex flex-wrap gap-2 items-center rounded-lg border border-slate-200 px-3 py-2 focus-within:border-brand">
              {to.map(r => (
                <span key={r} className="flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
                  {r}
                  <button onClick={() => setTo(t => t.filter(x => x !== r))} className="text-slate-400 hover:text-slate-700">×</button>
                </span>
              ))}
              <input value={toInput} onChange={e => setToInput(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter" && toInput) { setTo(t => [...t, toInput.toUpperCase()]); setToInput(""); e.preventDefault(); } }}
                placeholder="Add recipient..." className="flex-1 min-w-24 text-sm outline-none bg-transparent" />
            </div>
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1.5">CC (optional)</label>
            <input value={cc} onChange={e => setCc(e.target.value)} placeholder="Add CC recipients..."
              className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1.5">Subject</label>
            <input value={subject} onChange={e => setSubject(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand" />
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1.5">Message</label>
            <textarea value={message} onChange={e => setMessage(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3.5 py-3 text-sm outline-none focus:border-brand resize-none h-52 leading-relaxed" />
          </div>
          <div className="flex items-center justify-between pt-1">
            <button className="text-slate-400 hover:text-slate-600"><Paperclip className="h-5 w-5" /></button>
            <div className="flex gap-3">
              <button className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">Save draft</button>
              <button onClick={() => setSent(true)} className="rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-hover">Send</button>
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 space-y-5">
          <h2 className="text-base font-semibold text-slate-900">AI assistant</h2>
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Suggested subject</p>
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm text-slate-700">{AI_SUGGESTION.subject}</div>
          </div>
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Suggested body</p>
            <div className="rounded-lg border border-brand/30 bg-emerald-50/40 px-3.5 py-3 text-sm text-slate-700 whitespace-pre-line leading-relaxed">{AI_SUGGESTION.body}</div>
          </div>
          <button onClick={() => { setSubject(AI_SUGGESTION.subject); setMessage(AI_SUGGESTION.body); }}
            className="text-sm font-medium text-brand hover:underline">Use this draft</button>
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Tone</p>
            <div className="space-y-2">
              {TONES.map(t => (
                <label key={t} className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                  <input type="radio" name="tone" value={t} checked={tone === t} onChange={() => setTone(t)}
                    className="text-brand focus:ring-brand" />
                  {t}
                </label>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
