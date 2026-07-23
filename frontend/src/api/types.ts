// Domain model — the stable vocabulary the UI is written against.
//
// Components import ONLY from here. The shape of these types is chosen to match
// the sponsor-approved designs, NOT the current backend. Where a design shows a
// field the backend doesn't have yet (patient MRN, DOB, gender; inbox threads;
// the weekly workflow chart), the adapter in the matching src/api/*.ts file is
// responsible for producing it — today from a placeholder source, tomorrow from
// a real table — WITHOUT any component changing. That is the "accept any
// database later" seam: it lives entirely in the adapters, never in the UI.

export type Role = "front_desk" | "ops_manager" | "admin" | "doctor";

export interface CurrentUser {
  id: string;
  email: string;
  fullName: string;
  role: Role;
  isActive: boolean;
}

export interface ManagedUser extends CurrentUser {
  createdAt: string;
}

// ── Patients ────────────────────────────────────────────────────────────────
// Designs 4 & 5. The backend currently has no patient entity — only
// intake_cases with a free-text patient_name. Everything except `name` here is
// supplied by the patients adapter until a real patient database is added.
export type PatientStatus = "active" | "pending" | "inactive";

export interface Patient {
  id: string;
  mrn: string;
  name: string;
  dateOfBirth: string | null;
  gender: string | null;
  status: PatientStatus;
}

// ── Cases (intake) ──────────────────────────────────────────────────────────
export interface Case {
  id: string;
  patientName: string;
  contactReason: string;
  contactChannel: string;
  notes: string | null;
  status: string;
  createdAt: string;
  updatedAt: string;
}

// ── Consent ─────────────────────────────────────────────────────────────────
export type ConsentStatus = "pending" | "captured" | "withdrawn" | "not_required";

export interface Consent {
  id: string;
  caseId: string;
  status: ConsentStatus;
  capturedAt: string | null;
  consentType: string;
  notes: string | null;
  createdAt: string;
  updatedAt: string;
}

// Row shape for the consent queue (design 6), which shows patient + form +
// submitted date + a display status of pending / review / complete.
export type ConsentQueueStatus = "pending" | "review" | "complete";
export interface ConsentQueueRow {
  id: string;
  patientName: string;
  form: string;
  submitted: string;
  status: ConsentQueueStatus;
}

// ── Review tasks / routing (nav items, endpoints exist) ─────────────────────
export interface ReviewTask {
  id: string;
  caseId: string;
  taskType: "triage_review" | "consent_review" | "escalation_review";
  status: "pending" | "in_progress" | "completed" | "cancelled";
  assignedTo: string | null;
  notes: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface RoutingDecision {
  id: string;
  caseId: string;
  triageId: string;
  action: "admin_workflow" | "human_review" | "direct_escalation";
  targetQueue: string;
  escalated: boolean;
  createdAt: string;
}

// ── Audit ───────────────────────────────────────────────────────────────────
export interface AuditEvent {
  id: string;
  caseId: string | null;
  actorId: string | null;
  actorLabel: string | null;
  action: string;
  details: Record<string, unknown>;
  timestamp: string;
}

// ── Records / RAG (design 9) ────────────────────────────────────────────────
export interface RecordDocument {
  id: string;
  title: string;
  type: string;
  source: string;
  date: string;
  pages: number | null;
  confidentiality: string;
}

export interface RagAnswer {
  answer: string;
  refusalSource: "none" | "gate" | "llm";
  decision: string;
  citations: RecordDocument[];
}

// ── Messages / Inbox (design 10) ────────────────────────────────────────────
// No backend today. Served by the messages adapter's placeholder source.
export type MessagePriority = "urgent" | "normal" | "fyi";
export interface Message {
  id: string;
  fromName: string;
  fromInitials: string;
  toName: string;
  subject: string;
  body: string;
  priority: MessagePriority;
  unread: boolean;
  receivedLabel: string;
  threadReference: string;
  avatarColor: string;
}

// ── Dashboard (design 3) ────────────────────────────────────────────────────
export interface DashboardSummary {
  openCases: number;
  awaitingApproval: number;
  escalations: number;
  auditEvents: number;
  workflowByDay: { day: string; value: number }[];
  pendingReviews: { id: string; name: string; kind: string; isNew: boolean }[];
}
