export type Role = "front_desk" | "operator" | "admin" | "doctor";

export interface CurrentUser {
  id: string;
  email: string;
  fullName: string;
  role: Role;
  department: string | null;
  isActive: boolean;
  grantedPermissions: string[];
}

export interface ManagedUser extends CurrentUser {
  createdAt: string;
  lastActive: string | null;
}

export type PatientStatus = "active" | "pending" | "inactive";
export type Gender = "male" | "female" | "non_binary";

export interface Patient {
  id: string;
  mrn: string;
  name: string;
  dob: string;
  gender: Gender;
  status: PatientStatus;
  createdAt: string;
}

export interface PatientCounts { active: number; pending: number; inactive: number; }

export interface Case {
  id: string; patientName: string; contactReason: string;
  contactChannel: string; notes: string | null; status: string;
  createdAt: string; updatedAt: string;
}

export type ConsentStatus = "pending" | "captured" | "withdrawn" | "not_required";
export type ConsentQueueStatus = "pending" | "review" | "complete";

export interface Consent {
  id: string; caseId: string; status: ConsentStatus;
  capturedAt: string | null; consentType: string; notes: string | null;
  createdAt: string; updatedAt: string;
}

export interface ConsentQueueRow {
  id: string; patientName: string; form: string; submitted: string; status: ConsentQueueStatus;
}

export type TaskSource = "email" | "call";
export type TaskPriority = "low" | "medium" | "high" | "urgent";
export type TaskItemStatus = "pending" | "in_progress" | "completed" | "escalated";

export interface Task {
  id: string; caseId: string; assignedTo: string | null;
  source: TaskSource; priority: TaskPriority; status: TaskItemStatus;
  createdAt: string; updatedAt: string;
}

export interface TaskBoard {
  columns: Record<string, Task[]>;
  counts: { pending: number; in_progress: number; escalated: number; completed: number };
}

export interface AuditEvent {
  id: string; caseId: string | null; actorId: string | null;
  action: string; details: Record<string, unknown>; timestamp: string;
}

export interface ReviewTask {
  id: string; caseId: string;
  taskType: "triage_review" | "consent_review" | "escalation_review";
  status: "pending" | "in_progress" | "completed" | "cancelled";
  assignedTo: string | null; notes: string | null; createdAt: string; updatedAt: string;
}

export interface RecordDocument {
  id: string; title: string; type: string; source: string;
  date: string; pages: number | null; confidentiality: string;
}

export type MessagePriority = "urgent" | "normal" | "fyi";
export interface Message {
  id: string; fromName: string; fromInitials: string; toName: string;
  subject: string; body: string; priority: MessagePriority;
  unread: boolean; receivedLabel: string; threadReference: string; avatarColor: string;
}

export interface DashboardSummary {
  openCases: number; awaitingApproval: number; escalations: number; auditEvents: number;
  workflowByDay: { day: string; value: number }[];
  pendingReviews: { id: string; name: string; kind: string; isNew: boolean }[];
}

export type AppointmentStatus = "suggested" | "confirmed" | "cancelled";
export interface Appointment {
  id: string; caseId: string; doctorId: string; timeSlot: string;
  status: AppointmentStatus; createdAt: string; updatedAt: string;
}

export interface RagAnswer {
  answer: string;
  refusalSource: "none" | "gate" | "llm";
  decision: string;
  citations: RecordDocument[];
}
