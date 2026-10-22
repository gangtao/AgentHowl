"""认证（issue #114）：注册 / 邮箱验证 / 登录 / 登出 / me，cookie 会话，依赖注入。

安全口径：登录失败统一文案；/resend 不泄露邮箱存在性；禁用账号 403 且会话即时失效；
password_hash / session_id / 验证码明文永不进响应与日志。
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Mapping
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.runtime.mailer import Mailer, MailError
from app.runtime.ratelimit import RateLimiter
from app.runtime.users import (
    EMAIL_CODE_MAX_ATTEMPTS,
    User,
    UserConflictError,
    UserPublic,
    UserStore,
    hash_code,
    hash_password,
    is_expired,
    new_email_code,
    new_session,
    new_user_id,
    normalize_email,
    normalize_username,
    now_iso,
    validate_email,
    validate_password,
    validate_username,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_COOKIE = "agenthowl_session"
SESSION_MAX_AGE = 30 * 24 * 3600
VERIFY_SUBJECT = "AgentHowl 邮箱验证码"
# 登录时用户不存在也跑一次 scrypt，抹平时序差异（防用户枚举）
_DUMMY_HASH = hash_password("agenthowl-dummy-password")


class UnverifiedError(Exception):
    """登录时邮箱未验证；main.py 映射为 401 {"detail": "邮箱未验证", "reason": "unverified"}。"""


# ---------- 依赖 ----------


def get_users(request: Request) -> UserStore:
    users: UserStore = request.app.state.users
    return users


def user_from_cookie(users: UserStore, cookies: Mapping[str, str]) -> User | None:
    """cookie → 会话 → 用户；过期 / 用户不存在 / 已禁用 → None（并删掉该会话）。REST 与 WS 共用。"""
    sid = cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    session = users.get_session(sid)
    if session is None:
        return None
    user = users.get(session.user_id)
    if user is None or user.status != "active":
        users.delete_session(sid)
        return None
    return user


def current_user(request: Request) -> User | None:
    return user_from_cookie(get_users(request), request.cookies)


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def can_access(user: User, owner_id: str | None) -> bool:
    """归属规则（spec §5）：admin 恒 True；否则只看自己的；无主（旧数据）只有 admin 可见。"""
    return user.role == "admin" or (owner_id is not None and owner_id == user.user_id)


def client_ip(request: Request) -> str:
    if getattr(request.app.state, "trust_proxy", False):
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client is not None else "unknown"


def _limit(request: Request, rule: str) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    if not limiter.check(rule, client_ip(request)):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")


def _set_session(request: Request, response: Response, user: User) -> None:
    session = new_session(user.user_id)
    get_users(request).create_session(session)
    response.set_cookie(
        SESSION_COOKIE,
        session.session_id,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=bool(request.app.state.cookie_secure),
        path="/",
    )


async def _send_code(request: Request, user: User) -> None:
    users = get_users(request)
    mailer: Mailer = request.app.state.mailer
    code, record = new_email_code(user.user_id)
    old = users.get_email_code(user.user_id)
    if old is not None and not is_expired(old.expires_at):
        # 重发不重置尝试次数：否则可 5 次猜测 → 重发 → 再 5 次
        record = record.model_copy(update={"attempts": old.attempts})
    users.put_email_code(record)
    try:
        await mailer.send(
            user.email, VERIFY_SUBJECT, f"您的 AgentHowl 验证码：{code}，15 分钟内有效。"
        )
    except MailError as exc:
        logger.error("验证码邮件发送失败 user=%s：%s", user.username, exc)


# ---------- 请求 / 响应 ----------


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class RegisterResponse(BaseModel):
    user: UserPublic
    verification: Literal["email", "auto"]


class VerifyRequest(BaseModel):
    email: str
    code: str


class ResendRequest(BaseModel):
    email: str


class LoginRequest(BaseModel):
    identifier: str
    password: str


class LoginResponse(BaseModel):
    user: UserPublic


class OkResponse(BaseModel):
    ok: bool = True


# ---------- 端点 ----------


@router.post("/register", status_code=201)
async def register(req: RegisterRequest, request: Request) -> RegisterResponse:
    _limit(request, "register")
    username = normalize_username(req.username)
    email = normalize_email(req.email)
    try:
        validate_username(username)
        validate_email(email)
        validate_password(req.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    password_hash = await run_in_threadpool(hash_password, req.password)
    users = get_users(request)
    mailer: Mailer = request.app.state.mailer
    user = User(
        user_id=new_user_id(),
        username=username,
        email=email,
        password_hash=password_hash,
        email_verified_at=None if mailer.enabled else now_iso(),
        created_at=now_iso(),
    )
    try:
        users.put(user)
    except UserConflictError as exc:
        raise HTTPException(status_code=409, detail="用户名或邮箱已被占用") from exc
    if mailer.enabled:
        await _send_code(request, user)
        return RegisterResponse(user=user.public(), verification="email")
    return RegisterResponse(user=user.public(), verification="auto")


@router.post("/verify")
def verify(req: VerifyRequest, request: Request, response: Response) -> OkResponse:
    _limit(request, "verify")
    users = get_users(request)
    bad = HTTPException(status_code=400, detail="验证码无效或已过期")
    user = users.get_by_email(normalize_email(req.email))
    if user is None or user.email_verified_at is not None:
        raise bad
    record = users.get_email_code(user.user_id)
    if record is None or record.attempts >= EMAIL_CODE_MAX_ATTEMPTS:
        raise bad
    if is_expired(record.expires_at) or not hmac.compare_digest(
        record.code_hash, hash_code(req.code.strip())
    ):
        users.put_email_code(record.model_copy(update={"attempts": record.attempts + 1}))
        raise bad
    users.delete_email_code(user.user_id)
    verified = user.model_copy(update={"email_verified_at": now_iso()})
    users.put(verified)
    _set_session(request, response, verified)
    return OkResponse()


@router.post("/resend")
async def resend(req: ResendRequest, request: Request) -> OkResponse:
    _limit(request, "resend")
    users = get_users(request)
    mailer: Mailer = request.app.state.mailer
    user = users.get_by_email(normalize_email(req.email))
    if user is not None and user.email_verified_at is None and mailer.enabled:
        await _send_code(request, user)
    return OkResponse()  # 存在与否同样 200


@router.post("/login")
def login(req: LoginRequest, request: Request, response: Response) -> LoginResponse:
    _limit(request, "login")
    users = get_users(request)
    ident = req.identifier.strip()
    user = users.get_by_username(normalize_username(ident)) or users.get_by_email(
        normalize_email(ident)
    )
    if user is None:
        verify_password(req.password, _DUMMY_HASH)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已禁用")
    if user.email_verified_at is None:
        raise UnverifiedError()
    _set_session(request, response, user)
    return LoginResponse(user=user.public())


@router.post("/logout", status_code=204, response_class=Response)
def logout(request: Request) -> Response:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        get_users(request).delete_session(sid)
    resp = Response(status_code=204)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/me")
def me(user: User = Depends(require_user)) -> UserPublic:
    return user.public()
