"""管理员用户管理（issue #114）。守卫：不能改自己；不能让 active admin 归零。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import get_users, require_admin
from app.runtime.users import Role, Status, User, UserPublic, UserStore, now_iso

router = APIRouter(prefix="/admin", tags=["admin"])


class PatchUserRequest(BaseModel):
    role: Role | None = None
    status: Status | None = None


def _get(users: UserStore, user_id: str) -> User:
    u = users.get(user_id)
    if u is None:
        raise HTTPException(status_code=404, detail=f"用户不存在：{user_id}")
    return u


def _active_admins(users: UserStore) -> int:
    return sum(1 for u in users.list() if u.role == "admin" and u.status == "active")


@router.get("/users")
def list_users(
    _: User = Depends(require_admin), users: UserStore = Depends(get_users)
) -> list[UserPublic]:
    return [u.public() for u in users.list()]


@router.patch("/users/{user_id}")
def patch_user(
    user_id: str,
    body: PatchUserRequest,
    me: User = Depends(require_admin),
    users: UserStore = Depends(get_users),
) -> UserPublic:
    target = _get(users, user_id)
    if target.user_id == me.user_id:
        raise HTTPException(status_code=400, detail="不能修改自己的角色或状态")
    role = body.role if body.role is not None else target.role
    status = body.status if body.status is not None else target.status
    loses_admin = target.role == "admin" and target.status == "active"
    stays_admin = role == "admin" and status == "active"
    if loses_admin and not stays_admin and _active_admins(users) <= 1:
        raise HTTPException(status_code=400, detail="至少保留一个可用的管理员")
    updated = target.model_copy(update={"role": role, "status": status})
    users.put(updated)
    if status == "disabled":
        users.delete_sessions_of(target.user_id)
    return updated.public()


@router.post("/users/{user_id}/verify")
def verify_user(
    user_id: str, _: User = Depends(require_admin), users: UserStore = Depends(get_users)
) -> UserPublic:
    target = _get(users, user_id)
    if target.email_verified_at is None:
        target = target.model_copy(update={"email_verified_at": now_iso()})
        users.put(target)
    users.delete_email_code(target.user_id)
    return target.public()
