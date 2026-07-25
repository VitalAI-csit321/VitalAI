import { apiGet, apiPost } from "../lib/apiClient";
import type { DashboardSummary, Message, RecordDocument } from "./types";
import { placeholderMessages, placeholderWorkflowByDay } from "./_placeholder";

export const placeholderRecords: RecordDocument[] = [
  {id:"r1",title:"Discharge summary",type:"Clinical note",source:"Emergency Dept",date:"20 May 2026",pages:3,confidentiality:"Standard"},
  {id:"r2",title:"Lab results - FBC",type:"Laboratory",source:"Pathology",date:"19 May 2026",pages:1,confidentiality:"Standard"},
  {id:"r3",title:"Imaging - Chest X-ray",type:"Radiology",source:"Radiology",date:"19 May 2026",pages:2,confidentiality:"Standard"},
  {id:"r4",title:"Medication chart",type:"Prescription",source:"Pharmacy",date:"18 May 2026",pages:1,confidentiality:"Standard"},
  {id:"r5",title:"Admission notes",type:"Clinical note",source:"Ward 3B",date:"18 May 2026",pages:4,confidentiality:"Standard"},
];

export async function getDashboard(): Promise<DashboardSummary> {
  // Fetch real data in parallel, fall back gracefully
  const [intakeRes, taskRes, auditRes] = await Promise.allSettled([
    apiGet<{items:unknown[];total:number}>("/api/v1/intake?limit=1"),
    apiGet<{counts:{pending:number;in_progress:number;escalated:number;completed:number}}>("/api/v1/tasks/board"),
    apiGet<{total:number}>("/api/v1/audit?limit=1"),
  ]);

  const openCases = intakeRes.status==="fulfilled" ? intakeRes.value.total : 0;
  const counts = taskRes.status==="fulfilled" ? taskRes.value.counts : {pending:0,in_progress:0,escalated:0,completed:0};
  const auditEvents = auditRes.status==="fulfilled" ? auditRes.value.total : 0;

  // Also fetch review task summary for pending approvals
  const reviewRes = await apiGet<{total:number;pending:number}>("/api/v1/review-tasks/summary").catch(()=>({total:0,pending:0}));

  return {
    openCases,
    awaitingApproval: reviewRes.pending ?? (counts.pending + counts.in_progress),
    escalations: counts.escalated ?? 0,
    auditEvents,
    workflowByDay: placeholderWorkflowByDay,
    pendingReviews: [
      {id:"1",name:"Emily Zhang",kind:"Consent Review",isNew:true},
      {id:"2",name:"Marcus Williams",kind:"Treatment Auth",isNew:true},
      {id:"3",name:"Sarah Johnson",kind:"Medical Records",isNew:false},
      {id:"4",name:"David Chen",kind:"Insurance Claim",isNew:false},
    ],
  };
}

export async function listMessages(): Promise<Message[]> {
  return placeholderMessages;
}

export interface RagAnswer {
  answer: string;
  refusalSource: "none"|"gate"|"llm";
  decision: string;
  citations: RecordDocument[];
}

export async function ragQuery(input:{patient_id:string;question:string}): Promise<RagAnswer> {
  const res = await apiPost<{answer:string;refusal_source:"none"|"gate"|"llm";decision:string;citations:{chunk_id:string;doc_type:string;source_document_id:string;score:number;content:string}[]}>("/api/v1/rag/query",input);
  return {
    answer:res.answer, refusalSource:res.refusal_source, decision:res.decision,
    citations:res.citations.map(c=>({id:c.chunk_id,title:c.doc_type,type:c.doc_type,source:c.source_document_id,date:"",pages:null,confidentiality:"Standard"})),
  };
}
