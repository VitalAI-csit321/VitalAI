import { apiGet, apiLoginForm, apiPost, setToken, type ApiPage } from "../lib/apiClient";
import type { CurrentUser, ManagedUser, Role } from "./types";

interface RawUser {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

function toCurrentUser(raw: RawUser): CurrentUser {
  return {
    id: raw.id,
    email: raw.email,
    fullName: raw.full_name,
    role: raw.role,
    isActive: raw.is_active,
  };
}

function toManagedUser(raw: RawUser): ManagedUser {
  return { ...toCurrentUser(raw), createdAt: raw.created_at };
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
  const raw = await apiGet<RawUser>("/api/v1/auth/me");
  return toCurrentUser(raw);
}

export interface UserListParams {
  limit?: number;
  offset?: number;
  role?: Role[];
  is_active?: boolean;
  search?: string;
  [key: string]: unknown;
}

export async function listUsers(params: UserListParams = {}): Promise<ApiPage<ManagedUser>> {
  const page = await apiGet<ApiPage<RawUser>>("/api/v1/auth/users", params);
  return { ...page, items: page.items.map(toManagedUser) };
}

export async function registerUser(input: {
  email: string;
  password: string;
  full_name: string;
}): Promise<ManagedUser> {
  const raw = await apiPost<RawUser>("/api/v1/auth/register", input);
  return toManagedUser(raw);
}

export async function elevateUser(userId: string, newRole: Role): Promise<ManagedUser> {
  const raw = await apiPost<RawUser>(`/api/v1/auth/users/${userId}/elevate`, { new_role: newRole });
  return toManagedUser(raw);
}

export async function setUserActive(userId: string, active: boolean): Promise<ManagedUser> {
  const path = active
    ? `/api/v1/auth/users/${userId}/reactivate`
    : `/api/v1/auth/users/${userId}/deactivate`;
  const raw = await apiPost<RawUser>(path);
  return toManagedUser(raw);
}
