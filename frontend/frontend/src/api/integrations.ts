import { apiGet, apiPost } from "../lib/apiClient";

export interface MailboxStatus {
  enabled: boolean; account: string | null; needsSignin: boolean; lastCheckedAt: string | null;
}

export async function getMailboxStatus(): Promise<MailboxStatus> {
  const r = await apiGet<{ enabled: boolean; account: string | null; needs_signin: boolean; last_checked_at: string | null }>(
    "/api/v1/integrations/outlook",
  );
  return { enabled: r.enabled, account: r.account, needsSignin: r.needs_signin, lastCheckedAt: r.last_checked_at };
}

// Returns Microsoft's sign-in page; Microsoft sends the browser back to Settings.
export async function startMailboxSignIn(): Promise<string> {
  return (await apiPost<{ auth_url: string }>("/api/v1/integrations/outlook/connect")).auth_url;
}
