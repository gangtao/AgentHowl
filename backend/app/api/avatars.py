"""头像端点（issue #102）。上传：raw body（不用 multipart，免 python-multipart 依赖）；
读取：内容寻址，可永久缓存。无鉴权——头像随 /meta 对已终局对局公开，不是秘密。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.runtime.avatar_store import MAX_AVATAR_BYTES, AvatarStore, UnsupportedImageError

router = APIRouter(prefix="/avatars", tags=["avatars"])

_MEDIA = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


def get_avatar_store(request: Request) -> AvatarStore:
    store: AvatarStore = request.app.state.avatar_store
    return store


@router.put("")
async def upload_avatar(request: Request) -> dict[str, object]:
    """PUT raw 图片字节 → {avatar_id, bytes}。超 512 KB → 413；魔数不是 PNG/JPEG/WebP → 415。"""
    limit_kb = MAX_AVATAR_BYTES // 1024
    length = request.headers.get("content-length")
    if length is not None and length.isdecimal() and int(length) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail=f"头像不能超过 {limit_kb} KB")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_AVATAR_BYTES:
            raise HTTPException(status_code=413, detail=f"头像不能超过 {limit_kb} KB")
    try:
        avatar_id = get_avatar_store(request).put(bytes(data))
    except UnsupportedImageError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    return {"avatar_id": avatar_id, "bytes": len(data)}


@router.get("/{avatar_id}")
def fetch_avatar(avatar_id: str, request: Request) -> FileResponse:
    try:
        path = get_avatar_store(request).path_for(avatar_id)
    except ValueError:
        path = None  # 非法 id 与不存在同样 404，不回显校验信息
    if path is None:
        raise HTTPException(status_code=404, detail="头像不存在")
    return FileResponse(
        path,
        media_type=_MEDIA[avatar_id.rsplit(".", 1)[1]],
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
