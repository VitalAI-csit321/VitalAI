import { useRef, useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";

// A minimal signature pad drawn on canvas. Matches the design's bordered box;
// captured strokes are kept in component state (no signature backend exists).
function SignaturePad({ onChange }: { onChange: (hasInk: boolean) => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const hasInk = useRef(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = canvas.offsetWidth * ratio;
    canvas.height = canvas.offsetHeight * ratio;
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.scale(ratio, ratio);
      ctx.strokeStyle = "#0f172a";
      ctx.lineWidth = 2;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
    }
  }, []);

  function pos(e: React.PointerEvent) {
    const rect = canvasRef.current!.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function start(e: React.PointerEvent) {
    drawing.current = true;
    const ctx = canvasRef.current!.getContext("2d")!;
    const { x, y } = pos(e);
    ctx.beginPath();
    ctx.moveTo(x, y);
  }

  function move(e: React.PointerEvent) {
    if (!drawing.current) return;
    const ctx = canvasRef.current!.getContext("2d")!;
    const { x, y } = pos(e);
    ctx.lineTo(x, y);
    ctx.stroke();
    if (!hasInk.current) {
      hasInk.current = true;
      onChange(true);
    }
  }

  function end() {
    drawing.current = false;
  }

  return (
    <canvas
      ref={canvasRef}
      onPointerDown={start}
      onPointerMove={move}
      onPointerUp={end}
      onPointerLeave={end}
      className="h-40 w-full cursor-crosshair rounded-lg border border-slate-200 bg-slate-50 touch-none"
    />
  );
}

const CLAUSES = [
  {
    title: "1. I hereby consent to receive medical treatment at Royal Melbourne Hospital.",
    body: "This includes examination, diagnostic procedures, and treatment as deemed necessary by my healthcare provider.",
  },
  {
    title:
      "2. I understand that the practice of medicine is not an exact science and acknowledge that no guarantees have been made to me concerning the results of treatment.",
    body: "Healthcare professionals will use their best judgment in providing care.",
  },
  {
    title:
      "3. I authorize the hospital to disclose my medical information as necessary for treatment, payment, and healthcare operations.",
    body: "This may include sharing information with other healthcare providers involved in my care.",
  },
];

const CHECKS = [
  "I have read and understood the consent form",
  "I have had the opportunity to ask questions",
  "I consent to share my medical records with other healthcare providers as needed",
  "I consent to be contacted for research purposes",
];

export function ConsentCapturePage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [checked, setChecked] = useState<boolean[]>([true, true, false, false]);
  const [signed, setSigned] = useState(false);

  function toggle(i: number) {
    setChecked((c) => c.map((v, idx) => (idx === i ? !v : v)));
  }

  const today = new Date().toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <h1 className="text-2xl font-bold text-slate-900">Consent capture</h1>
        <span className="rounded-md bg-amber-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-amber-700">
          {signed ? "Signed" : "Awaiting signature"}
        </span>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="rounded-xl border border-slate-200 bg-white p-6">
          <h2 className="text-base font-semibold text-slate-900">Patient consent</h2>
          <h3 className="mt-3 text-sm font-semibold text-slate-800">General treatment</h3>

          <div className="mt-4 space-y-4">
            {CLAUSES.map((c) => (
              <div key={c.title}>
                <p className="text-sm text-slate-800">{c.title}</p>
                <p className="mt-1 text-xs text-slate-500">{c.body}</p>
              </div>
            ))}
          </div>

          <div className="my-5 h-px bg-slate-100" />

          <div className="space-y-3">
            {CHECKS.map((label, i) => (
              <label key={label} className="flex items-start gap-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={checked[i]}
                  onChange={() => toggle(i)}
                  className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand"
                />
                {label}
              </label>
            ))}
          </div>
        </div>

        <div className="space-y-6">
          <div className="rounded-xl border border-slate-200 bg-white p-6">
            <h2 className="text-base font-semibold text-slate-900">Digital signature</h2>
            <div className="mt-4">
              <SignaturePad onChange={setSigned} />
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-6">
            <h2 className="text-base font-semibold text-slate-900">Witness</h2>
            <div className="mt-4 space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-slate-500">Name</span>
                <span className="font-medium text-slate-900">
                  {user ? `Dr ${user.fullName}` : "—"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Date</span>
                <span className="font-medium text-slate-900">{today}</span>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            All actions are logged to the audit trail for compliance purposes.
          </div>
        </div>
      </div>

      <div className="mt-6 flex gap-3">
        <button
          onClick={() => navigate(-1)}
          className="rounded-lg border border-slate-200 bg-white px-5 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Back
        </button>
        <button
          onClick={() => navigate("/consent/success")}
          className="rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-hover"
        >
          Submit consent
        </button>
      </div>
    </div>
  );
}
