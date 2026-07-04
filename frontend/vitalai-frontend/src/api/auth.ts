import apiClient from "./client";
import type { Token, User, LoginRequest, RegisterRequest } from "../types";

/**
 * POST /api/v1/auth/login
 * Uses OAuth2PasswordRequestForm — must be form-encoded, not JSON.
 * Backend reads `username` field (not `email`) for the email value.
 */
export async function login(payload: LoginRequest): Promise<Token> {
  const form = new URLSearchParams();
  form.append("username", payload.email);
  form.append("password", payload.password);

  const res = await apiClient.post<Token>("/api/v1/auth/login", form, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  return res.data;
}

/**
 * POST /api/v1/auth/register
 * Backend always assigns role = front_desk regardless of what is sent.
 */
export async function register(payload: RegisterRequest): Promise<User> {
  const res = await apiClient.post<User>("/api/v1/auth/register", payload);
  return res.data;
}

/**
 * GET /api/v1/auth/me
 * Validates stored token and returns the current user object.
 */
export async function getMe(): Promise<User> {
  const res = await apiClient.get<User>("/api/v1/auth/me");
  return res.data;
}
