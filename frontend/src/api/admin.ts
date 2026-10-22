// 管理员用户管理 API（issue #114）。

import type { UserPublic } from "./auth";
import { req } from "./rest";

export function listUsers(): Promise<UserPublic[]> {
  return req<UserPublic[]>("GET", "/admin/users");
}

export function patchUser(
  userId: string,
  body: { role?: "admin" | "user"; status?: "active" | "disabled" },
): Promise<UserPublic> {
  return req<UserPublic>("PATCH", `/admin/users/${userId}`, { body });
}

export function verifyUser(userId: string): Promise<UserPublic> {
  return req<UserPublic>("POST", `/admin/users/${userId}/verify`);
}
