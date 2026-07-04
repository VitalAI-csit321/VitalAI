// ─── ROLES — exact values from backend app/models/user.py UserRole StrEnum ──
export const ROLES = {
  FRONT_DESK:  "front_desk",
  OPS_MANAGER: "ops_manager",
  ADMIN:       "admin",
} as const;

export type UserRole = (typeof ROLES)[keyof typeof ROLES];

// ─── Auth ─────────────────────────────────────────────────────────────────────
// POST /api/v1/auth/register  — role field sent but backend ignores it (always front_desk)
export interface RegisterRequest {
  email: string;
  password: string;       // min 8 chars
  full_name: string;
}

// POST /api/v1/auth/login — form-encoded OAuth2PasswordRequestForm
export interface LoginRequest {
  email: string;
  password: string;
}

// GET /api/v1/auth/me  →  UserOut
export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

// POST /api/v1/auth/login  →  Token
export interface Token {
  access_token: string;
  token_type: string;
}

// ─── Intake ───────────────────────────────────────────────────────────────────
// POST /api/v1/intake  body: IntakeCreate
export interface IntakeCreate {
  patient_name: string;       // min 1, max 255
  contact_reason: string;     // min 1
  contact_channel: string;    // min 1, max 50  e.g. "walk_in" | "phone" | "email"
  notes?: string | null;
}

// IntakeCaseOut — what comes back
export type IntakeStatus =
  | "intake_received"
  | "intake_incomplete"
  | "consent_pending"
  | "consent_captured"
  | "context_ready"
  | "context_insufficient"
  | "triage_routine"
  | "triage_time_sensitive"
  | "triage_immediate"
  | "routed"
  | "escalated";

export interface IntakeCase {
  id: string;
  patient_name: string;
  contact_reason: string;
  contact_channel: string;
  notes: string | null;
  status: IntakeStatus;
  created_at: string;
  updated_at: string;
}

// ─── Consent ──────────────────────────────────────────────────────────────────
// POST /api/v1/consent  body: ConsentCreate
export interface ConsentCreate {
  case_id: string;                            // UUID of the intake case
  consent_type?: string;                      // default "administrative"
  notes?: string | null;
}

export type ConsentStatus = "pending" | "captured" | "withdrawn" | "not_required";

// ConsentOut
export interface ConsentRecord {
  id: string;
  case_id: string;
  status: ConsentStatus;
  captured_at: string | null;
  consent_type: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

// ─── Triage ───────────────────────────────────────────────────────────────────
// POST /api/v1/triage  body: TriageRequest
export interface TriageRequest {
  case_id: string;
  contact_reason: string;
  keywords?: string[];
  patient_priority_flags?: string[];
}

export type TriageCategory =
  | "routine"
  | "time_sensitive"
  | "immediate"
  | "low_confidence_manual_review";

export type RoutingAction = "admin_workflow" | "human_review" | "direct_escalation";

// TriageResponse
export interface TriageResponse {
  triage_id: string;
  case_id: string;
  category: TriageCategory;
  confidence: number;
  rationale: string;
  routing_action: RoutingAction;
  target_queue: string;
  escalated: boolean;
}

// ─── Audit ────────────────────────────────────────────────────────────────────
// GET /api/v1/audit/by-case/{case_id}  →  AuditEventOut[]
export interface AuditEvent {
  id: string;
  case_id: string | null;
  actor_id: string | null;
  actor_label: string | null;
  action: string;
  details: Record<string, unknown>;
  timestamp: string;
}

// ─── API error ────────────────────────────────────────────────────────────────
export interface ApiError {
  detail: string;
}
