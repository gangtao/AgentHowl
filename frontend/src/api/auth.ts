// 认证 API（issue #114）：cookie 会话由浏览器自动携带（req 已设 credentials）。

import { req } from "./rest";

export interface UserPublic {
  user_id: string;
  username: string;
  email: string;
  role: "admin" | "user";
  status: "active" | "disabled";
  email_verified: boolean;
  created_at: string;
}

export interface RegisterResponse {
  user: UserPublic;
  verification: "email" | "auto";
}

export function register(username: string, email: string, password: string): Promise<RegisterResponse> {
  return req<RegisterResponse>("POST", "/auth/register", { body: { username, email, password } });
}

export function verify(email: string, code: string): Promise<{ ok: boolean }> {
  return req<{ ok: boolean }>("POST", "/auth/verify", { body: { email, code } });
}

export function resend(email: string): Promise<{ ok: boolean }> {
  return req<{ ok: boolean }>("POST", "/auth/resend", { body: { email } });
}

export async function login(identifier: string, password: string): Promise<UserPublic> {
  const r = await req<{ user: UserPublic }>("POST", "/auth/login", { body: { identifier, password } });
  return r.user;
}

export function logout(): Promise<void> {
  return req<void>("POST", "/auth/logout");
}

export function me(): Promise<UserPublic> {
  return req<UserPublic>("GET", "/auth/me");
}
