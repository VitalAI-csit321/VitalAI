import apiClient from "./client";
import type { TriageRequest, TriageResponse } from "../types";

/**
 * POST /api/v1/triage
 * Submits a case for triage classification.
 * Returns category, confidence, rationale, and routing action.
 * Will 422 if consent is not yet captured for the case (ConsentGatingError).
 */
export async function runTriage(payload: TriageRequest): Promise<TriageResponse> {
  const res = await apiClient.post<TriageResponse>("/api/v1/triage", payload);
  return res.data;
}
