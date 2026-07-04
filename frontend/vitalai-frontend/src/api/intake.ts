import apiClient from "./client";
import type { IntakeCase, IntakeCreate } from "../types";

/**
 * POST /api/v1/intake
 * Creates a new intake case. Returns IntakeCaseOut.
 */
export async function createIntake(payload: IntakeCreate): Promise<IntakeCase> {
  const res = await apiClient.post<IntakeCase>("/api/v1/intake", payload);
  return res.data;
}

/**
 * GET /api/v1/intake/{case_id}
 */
export async function getIntakeCase(caseId: string): Promise<IntakeCase> {
  const res = await apiClient.get<IntakeCase>(`/api/v1/intake/${caseId}`);
  return res.data;
}
