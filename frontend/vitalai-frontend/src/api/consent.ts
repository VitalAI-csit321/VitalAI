import apiClient from "./client";
import type { ConsentCreate, ConsentRecord } from "../types";

/**
 * POST /api/v1/consent
 * Creates a pending consent record for a case.
 */
export async function createConsent(payload: ConsentCreate): Promise<ConsentRecord> {
  const res = await apiClient.post<ConsentRecord>("/api/v1/consent", payload);
  return res.data;
}

/**
 * GET /api/v1/consent/by-case/{case_id}
 * Fetches the consent record for a given intake case.
 */
export async function getConsentByCase(caseId: string): Promise<ConsentRecord> {
  const res = await apiClient.get<ConsentRecord>(`/api/v1/consent/by-case/${caseId}`);
  return res.data;
}

/**
 * POST /api/v1/consent/{consent_id}/capture
 * Moves consent from pending → captured.
 */
export async function captureConsent(consentId: string): Promise<ConsentRecord> {
  const res = await apiClient.post<ConsentRecord>(`/api/v1/consent/${consentId}/capture`);
  return res.data;
}

/**
 * POST /api/v1/consent/{consent_id}/withdraw
 * Moves consent to withdrawn.
 */
export async function withdrawConsent(consentId: string): Promise<ConsentRecord> {
  const res = await apiClient.post<ConsentRecord>(`/api/v1/consent/${consentId}/withdraw`);
  return res.data;
}
