import { apiGet, apiLoginForm, apiPost, setToken } from "../lib/apiClient";
import type { CurrentUser, ManagedUser, Role } from "./types";

interface RawUser {
  id: string; email: string; full_name: string; role: Role;
  department: string | null; is_active: boolean; created_at: string;
  granted_permissions?: string[];
}

function toCurrentUser(raw: RawUser): CurrentUser {
  return {
    id: raw.id, email: raw.email, fullName: raw.full_name, role: raw.role,
    department: raw.department, isActive: raw.is_active,
    grantedPermissions: raw.granted_permissions ?? [],
  };
}

function toManagedUser(raw: RawUser, lastActive: string | null = null): ManagedUser {
  return { ...toCurrentUser(raw), createdAt: raw.created_at, lastActive };
}

export async function login(email: string, password: string): Promise<CurrentUser> {
  const { access_token } = await apiLoginForm(email, password);
  setToken(access_token);
  return getMe();
}

export async function getMe(): Promise<CurrentUser> {
  return toCurrentUser(await apiGet<RawUser>("/api/v1/auth/me"));
}

export interface UserListParams { limit?: number; offset?: number; search?: string; [key: string]: unknown; }

export async function listUsers(params: UserListParams = {}): Promise<{ items: ManagedUser[]; total: number }> {
  const page = await apiGet<{ items: unknown[]; total: number }>("/api/v1/auth/users", params);
  const items = page.items.map((row: unknown) => {
    if (Array.isArray(row)) return toManagedUser(row[0] as RawUser, row[1] as string | null);
    return toManagedUser(row as RawUser, null);
  });
  return { items, total: page.total };
}

export async function registerUser(input: { email: string; password: string; full_name: string }): Promise<ManagedUser> {
  return toManagedUser(await apiPost<RawUser>("/api/v1/auth/register", input));
}

export async function elevateUser(userId: string, newRole: Role): Promise<ManagedUser> {
  return toManagedUser(await apiPost<RawUser>(`/api/v1/auth/users/${userId}/elevate`, { new_role: newRole }));
}
