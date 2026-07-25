import { useRef, useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { createConsent, captureConsent } from "../api/consent";
import { apiGet } from "../lib/apiClient";

function SignaturePad({onChange}:{onChange:(v:boolean)=>void}) {
  const ref=useRef<HTMLCanvasElement>(null); const drawing=useRef(false); const inked=useRef(false);
  useEffect(()=>{const c=ref.current;if(!c)return;const r=window.devicePixelRatio||1;c.width=c.offsetWidth*r;c.height=c.offsetHeight*r;const ctx=c.getContext("2d");if(ctx){ctx.scale(r,r);ctx.strokeStyle="#0f172a";ctx.lineWidth=2;ctx.lineCap="round";ctx.lineJoin="round";}},[]);
  function pos(e:React.PointerEvent){const r=ref.current!.getBoundingClientRect();return{x:e.clientX-r.left,y:e.clientY-r.top};}
  function start(e:React.PointerEvent){drawing.current=true;const ctx=ref.current!.getContext("2d")!;const{x,y}=pos(e);ctx.beginPath();ctx.moveTo(x,y);}
  function move(e:React.PointerEvent){if(!drawing.current)return;const ctx=ref.current!.getContext("2d")!;const{x,y}=pos(e);ctx.lineTo(x,y);ctx.stroke();if(!inked.current){inked.current=true;onChange(true);}}
  function end(){drawing.current=false;}
  return <canvas ref={ref} onPointerDown={start} onPointerMove={move} onPointerUp={end} onPointerLeave={end} className="h-40 w-full cursor-crosshair rounded-lg border border-slate-200 bg-slate-50 touch-none"/>;
}

const CLAUSES=["I hereby consent to receive medical treatment at Royal Melbourne Hospital, including examination, diagnostic procedures, and treatment deemed necessary by my healthcare provider.","I understand that no guarantees have been made concerning results of treatment and healthcare professionals will use their best judgment.","I authorize the hospital to disclose my medical information as necessary for treatment, payment, and healthcare operations."];
const CHECKS=["I have read and understood the consent form","I have had the opportunity to ask questions","I consent to share my records with other healthcare providers as needed","I consent to be contacted for research purposes"];

export function ConsentCapturePage() {
  const navigate=useNavigate(); const [params]=useSearchParams(); const {user}=useAuth();
  const [checked,setChecked]=useState([true,true,false,false]);
  const [signed,setSigned]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const today=new Date().toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric"});

  async function submit() {
    setBusy(true);setError(null);
    try {
      let caseId=params.get("case");
      if(!caseId){const r=await apiGet<{items:{id:string}[]}>("/api/v1/intake?limit=1");caseId=r.items[0]?.id;}
      if(!caseId)throw new Error("No case found");
      const c=await createConsent({case_id:caseId,consent_type:"general_treatment"});
      await captureConsent(c.id);
      navigate("/consent/success");
    } catch{setError("Could not submit consent. Please try again.");setBusy(false);}
  }

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <h1 className="text-2xl font-bold text-slate-900">Consent capture</h1>
        <span className={`rounded-md px-3 py-1 text-xs font-semibold uppercase ${signed?"bg-emerald-100 text-emerald-700":"bg-amber-100 text-amber-700"}`}>{signed?"Signed":"Awaiting signature"}</span>
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="rounded-xl border border-slate-200 bg-white p-6">
          <h2 className="font-semibold text-slate-900">Patient consent — General treatment</h2>
          <div className="mt-4 space-y-4">{CLAUSES.map((c,i)=><p key={i} className="text-sm text-slate-700">{i+1}. {c}</p>)}</div>
          <div className="my-5 h-px bg-slate-100"/>
          <div className="space-y-3">{CHECKS.map((label,i)=>(
            <label key={label} className="flex items-start gap-3 text-sm text-slate-700 cursor-pointer">
              <input type="checkbox" checked={checked[i]} onChange={()=>setChecked(c=>c.map((v,idx)=>idx===i?!v:v))} className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand"/>{label}
            </label>
          ))}</div>
        </div>
        <div className="space-y-5">
          <div className="rounded-xl border border-slate-200 bg-white p-6"><h2 className="font-semibold text-slate-900 mb-4">Digital signature</h2><SignaturePad onChange={setSigned}/></div>
          <div className="rounded-xl border border-slate-200 bg-white p-6">
            <h2 className="font-semibold text-slate-900 mb-4">Witness</h2>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-slate-500">Name</span><span className="font-medium text-slate-900">{user?`Dr ${user.fullName}`:"—"}</span></div>
              <div className="flex justify-between"><span className="text-slate-500">Date</span><span className="font-medium text-slate-900">{today}</span></div>
            </div>
          </div>
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">All actions are logged to the audit trail.</div>
        </div>
      </div>
      {error&&<p className="mt-4 text-sm text-red-600">{error}</p>}
      <div className="mt-6 flex gap-3">
        <button onClick={()=>navigate(-1)} className="rounded-lg border border-slate-200 bg-white px-5 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">Back</button>
        <button onClick={submit} disabled={busy||!signed} className="rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50">{busy?"Submitting…":"Submit consent"}</button>
      </div>
    </div>
  );
}
