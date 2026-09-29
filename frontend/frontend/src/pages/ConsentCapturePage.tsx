import { useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { createConsent, captureConsent, consentTypeLabel } from "../api/consent";
import { apiGet } from "../lib/apiClient";
import { SignaturePad } from "../components/SignaturePad";


export const CLAUSES=["I hereby consent to receive medical treatment at GreenCare Family Medical Clinic, including examination, diagnostic procedures, and treatment deemed necessary by my healthcare provider.","I understand that no guarantees have been made concerning results of treatment and healthcare professionals will use their best judgment.","I authorize GreenCare Family Medical Clinic to disclose my medical information as necessary for treatment, payment, and healthcare operations."];
const CHECKS=["I have read and understood the consent form","I have had the opportunity to ask questions","I consent to share my records with other healthcare providers as needed","I consent to be contacted for research purposes"];

export function ConsentCapturePage() {
  const navigate=useNavigate(); const [params]=useSearchParams(); const {user}=useAuth();
  const [checked,setChecked]=useState([true,true,false,false]);
  const [signed,setSigned]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const canvasRef=useRef<HTMLCanvasElement>(null);
  const today=new Date().toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric"});
  const consentType=params.get("type") ?? "general_treatment";
  const typeLabel=consentTypeLabel(consentType);

  async function submit() {
    const caseId=params.get("case");
    if(!caseId){setError("No case found");return;}
    setBusy(true);setError(null);
    try {
      const caseDetail = await apiGet<{patient_name:string|null}>(`/api/v1/intake/${caseId}`);
      const c=await createConsent({case_id:caseId,consent_type:consentType});
      const signature=canvasRef.current?.toDataURL("image/png") ?? "";
      await captureConsent(c.id, { checks: CHECKS.map((label,i)=>({label,checked:checked[i]})), signature });
      navigate("/consent/success", { state: { patientName: caseDetail.patient_name ?? "Unknown patient", formType: typeLabel, timestamp: new Date().toISOString() } });
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
          <h2 className="font-semibold text-slate-900">Patient consent — {typeLabel}</h2>
          <div className="mt-4 space-y-4">{CLAUSES.map((c,i)=><p key={i} className="text-sm text-slate-700">{i+1}. {c}</p>)}</div>
          <div className="my-5 h-px bg-slate-100"/>
          <div className="space-y-3">{CHECKS.map((label,i)=>(
            <label key={label} className="flex items-start gap-3 text-sm text-slate-700 cursor-pointer">
              <input type="checkbox" checked={checked[i]} onChange={()=>setChecked(c=>c.map((v,idx)=>idx===i?!v:v))} className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand"/>{label}
            </label>
          ))}</div>
        </div>
        <div className="space-y-5">
          <div className="rounded-xl border border-slate-200 bg-white p-6"><h2 className="font-semibold text-slate-900 mb-4">Digital signature</h2><SignaturePad onChange={setSigned} canvasRef={canvasRef}/></div>
          <div className="rounded-xl border border-slate-200 bg-white p-6">
            <h2 className="font-semibold text-slate-900 mb-4">Witness</h2>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-slate-500">Name</span><span className="font-medium text-slate-900">{user?(user.role==="doctor"?`Dr ${user.fullName}`:user.fullName):"—"}</span></div>
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
