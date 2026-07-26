import { apiGet } from "../lib/apiClient";
import type { AuditEvent } from "./types";

interface RawAuditEvent {
  id: string; case_id: string | null; actor_id: string | null;
  action: string; details: Record<string, unknown>; timestamp: string;
}

function toAuditEvent(r: RawAuditEvent): AuditEvent {
  return { id: r.id, caseId: r.case_id, actorId: r.actor_id, action: r.action, details: r.details, timestamp: r.timestamp };
}

export interface AuditListParams { limit?: number; offset?: number; search?: string; action?: string; [key: string]: unknown; }

export async function listAuditEvents(params: AuditListParams = {}): Promise<{ items: AuditEvent[]; total: number }> {
  const res = await apiGet<{ items: RawAuditEvent[]; total: number }>("/api/v1/audit", params);
  return { items: res.items.map(toAuditEvent), total: res.total };
}

export async function getAuditEvent(eventId: string): Promise<AuditEvent> {
  return toAuditEvent(await apiGet<RawAuditEvent>(`/api/v1/audit/${eventId}`));
}

export async function getAuditForCase(caseId: string): Promise<AuditEvent[]> {
  const res = await apiGet<RawAuditEvent[]>(`/api/v1/audit/by-case/${caseId}`);
  return res.map(toAuditEvent);
}
