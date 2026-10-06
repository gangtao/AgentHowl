// 头像上传/引用（issue #102）：PUT raw 字节；读取走内容寻址 URL，可永久缓存。

import { API_BASE, ApiError } from "./rest";

export const MAX_AVATAR_BYTES = 512 * 1024;
export const AVATAR_ACCEPT = "image/png,image/jpeg,image/webp";

export interface AvatarUpload {
  avatar_id: string;
  bytes: number;
}

export function avatarUrl(avatarId: string): string {
  return `${API_BASE}/avatars/${avatarId}`;
}

export async function uploadAvatar(file: File): Promise<AvatarUpload> {
  const res = await fetch(`${API_BASE}/avatars`, {
    method: "PUT",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* 非 JSON 错误体 */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as AvatarUpload;
}
