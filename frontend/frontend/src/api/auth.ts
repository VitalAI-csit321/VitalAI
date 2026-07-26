import { apiGet, apiLoginForm, apiPost, setToken } from "../lib/apiClient";
import type { CurrentUser, ManagedUser, Role } from "./types";

interface RawUser {
  id: string; email: string; full_name: string; role: Role;
  department: string | null; is_active: boolean; created_at: string;
  granted_permissions?: string[]; last_active?: string | null;
}

function toCurrentUser(raw: RawUser): CurrentUser {
  return {
    id: raw.id, email: raw.email, fullName: raw.full_name, role: raw.role,
    department: raw.department, isActive: raw.is_active,
    grantedPermissions: raw.granted_permissions ?? [],
  };
}

function toManagedUser(raw: RawUser): ManagedUser {
  return { ...toCurrentUser(raw), createdAt: raw.created_at, lastActive: raw.last_active ?? null };
}

export async function login(email: string, password: string): Promise<CurrentUser> {
  const { access_token } = await apiLoginForm(email, password);
  setToken(access_token);
  return getMe();
}

export function logout(): void {
  setToken(null);
}

export async function getMe(): Promise<CurrentUser> {
  return toCurrentUser(await apiGet<RawUser>("/api/v1/auth/me"));
}

export interface UserListParams { limit?: number; offset?: number; search?: string; [key: string]: unknown; }

export async function listUsers(params: UserListParams = {}): Promise<{ items: ManagedUser[]; total: number }> {
  const page = await apiGet<{ items: RawUser[]; total: number }>("/api/v1/auth/users", params);
  return { items: page.items.map(toManagedUser), total: page.total };
}

export async function registerUser(input: { email: string; password: string; full_name: string }): Promise<ManagedUser> {
  return toManagedUser(await apiPost<RawUser>("/api/v1/auth/register", input));
}

export async function elevateUser(userId: string, newRole: Role): Promise<ManagedUser> {
  return toManagedUser(await apiPost<RawUser>(`/api/v1/auth/users/${userId}/elevate`, { new_role: newRole }));
}

export async function updateUserDepartment(userId: string, department: string): Promise<ManagedUser> {
  return toManagedUser(await apiPost<RawUser>(`/api/v1/auth/users/${userId}/department`, { department }));
}

export async function setUserActive(userId: string, isActive: boolean): Promise<ManagedUser> {
  return toManagedUser(await apiPost<RawUser>(`/api/v1/auth/users/${userId}/active`, { is_active: isActive }));
}

export async function getUserGrants(userId: string): Promise<string[]> {
  const res = await apiGet<{ permissions: string[] }>(`/api/v1/auth/users/${userId}/grants`);
  return res.permissions;
}

