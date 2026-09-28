import { apiGet, apiPost } from "../lib/apiClient";

// The public registration form. No login: the token in the URL is the credential.

export interface RegistrationLink {
  email: string;
  needsPreferredDay: boolean;
  statements: string[];
}

export interface RegistrationForm {
  name: string;
  dob: string;
  phone: string;
  gender: string;
  address: string;
  emergency_contact_name: string;
  emergency_contact_phone: string;
  preferred_language: string;
  preferred_communication: string;
  preferred_day: string;
  part_of_day: "morning" | "afternoon" | "any";
}

const path = (token: string) => `/api/v1/public/registration/${encodeURIComponent(token)}`;

export async function getRegistrationLink(token: string): Promise<RegistrationLink> {
  const raw = await apiGet<{ email: string; needs_preferred_day: boolean; statements: string[] }>(
    path(token),
  );
  return { email: raw.email, needsPreferredDay: raw.needs_preferred_day, statements: raw.statements };
}

export async function submitRegistration(
  token: string,
  form: RegistrationForm & { agree_data: true; agree_contact: true; signature: string },
): Promise<void> {
  await apiPost(path(token), form);
}
