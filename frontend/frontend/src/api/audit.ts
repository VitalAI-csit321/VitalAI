import { apiGet, getToken } from "../lib/apiClient";
import type { AuditEvent } from "./types";

interface RawAuditEvent {
  id: string; case_id: string | null; actor_id: string | null; actor_label: string | null;
  actor_role: string | null; action: string; details: Record<string, unknown>; timestamp: string;
  risk_score: number | null; risk_level: "High" | "Medium" | "Low"; outcome: string | null;
  ip_address: string | null; session_id: string | null; event_hash: string | null;
  predecessor_hash: string | null;
}

function toAuditEvent(r: RawAuditEvent): AuditEvent {
  return {
    id: r.id, caseId: r.case_id, actorId: r.actor_id, actorLabel: r.actor_label,
    actorRole: r.actor_role, action: r.action, details: r.details, timestamp: r.timestamp,
    riskScore: r.risk_score, riskLevel: r.risk_level, outcome: r.outcome,
    ipAddress: r.ip_address, sessionId: r.session_id, eventHash: r.event_hash,
    predecessorHash: r.predecessor_hash,
  };
}

export interface AuditListParams {
  limit?: number; offset?: number; action?: string;
  riskLevel?: "High" | "Medium" | "Low"; outcome?: string; caseId?: string;
  [key: string]: unknown;
}

function toQueryParams(params: AuditListParams): Record<string, unknown> {
  return {
    limit: params.limit, offset: params.offset, action: params.action,
    risk_level: params.riskLevel, outcome: params.outcome, case_id: params.caseId,
  };
}

export async function listAuditEvents(
  params: AuditListParams = {},
): Promise<{ items: AuditEvent[]; total: number }> {
  const res = await apiGet<{ items: RawAuditEvent[]; total: number }>(
    "/api/v1/audit",
    toQueryParams(params),
  );
  return { items: res.items.map(toAuditEvent), total: res.total };
}

export async function getAuditEvent(eventId: string): Promise<AuditEvent> {
  return toAuditEvent(await apiGet<RawAuditEvent>(`/api/v1/audit/${eventId}`));
}

export async function getAuditForCase(caseId: string): Promise<AuditEvent[]> {
  const res = await apiGet<RawAuditEvent[]>(`/api/v1/audit/by-case/${caseId}`);
  return res.map(toAuditEvent);
}

export async function verifyAuditChain(): Promise<{
  valid: boolean; checkedCount: number; firstBreakEventId: string | null;
}> {
  const res = await apiGet<{
    valid: boolean; checked_count: number; first_break_event_id: string | null;
  }>("/api/v1/audit/verify");
  return { valid: res.valid, checkedCount: res.checked_count, firstBreakEventId: res.first_break_event_id };
}

const BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ??
  "http://localhost:8000";

export async function downloadAuditCsv(params: AuditListParams = {}): Promise<void> {
  const url = new URL(BASE_URL + "/api/v1/audit");
  url.searchParams.set("format", "csv");
  const queryParams = toQueryParams(params);
  for (const [key, value] of Object.entries(queryParams)) {
    if (value === undefined || value === null || value === "") continue;
    url.searchParams.set(key, String(value));
  }

  const token = getToken();
  const res = await fetch(url.toString(), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`CSV export failed (${res.status})`);

  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = "audit_events.csv";
  link.click();
  URL.revokeObjectURL(objectUrl);
}
