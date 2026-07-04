import apiClient from "./client";
import type { AuditEvent } from "../types";

/**
 * GET /api/v1/audit/by-case/{case_id}
 * Returns all audit events for a case. Requires ADMIN role.
 */
export async function getAuditByCase(caseId: string): Promise<AuditEvent[]> {
  const res = await apiClient.get<AuditEvent[]>(`/api/v1/audit/by-case/${caseId}`);
  return res.data;
}
