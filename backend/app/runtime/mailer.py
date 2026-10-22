"""邮件发送（issue #114）：标准库 smtplib，在线程里发；未配置 SMTP → NullMailer（注册免验证）。"""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
from collections.abc import Mapping
from email.message import EmailMessage
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class MailError(RuntimeError):
    """发送失败（网络 / 认证）；文案不含密码。"""


class MailConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str
    port: int = 587
    user: str | None = None
    password: str | None = Field(default=None, repr=False)
    sender: str
    starttls: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> MailConfig | None:
        e = os.environ if env is None else env
        host = e.get("AGENTHOWL_SMTP_HOST", "").strip()
        if not host:
            return None
        sender = e.get("AGENTHOWL_SMTP_FROM", "").strip()
        if not sender:
            raise ValueError("配置了 AGENTHOWL_SMTP_HOST 就必须配置 AGENTHOWL_SMTP_FROM")
        return cls(
            host=host,
            port=int(e.get("AGENTHOWL_SMTP_PORT", "587")),
            user=e.get("AGENTHOWL_SMTP_USER") or None,
            password=e.get("AGENTHOWL_SMTP_PASSWORD") or None,
            sender=sender,
            starttls=e.get("AGENTHOWL_SMTP_STARTTLS", "1").strip().lower()
            not in ("0", "false", "no", "off"),
        )


class Mailer(Protocol):
    @property
    def enabled(self) -> bool: ...

    async def send(self, to: str, subject: str, body: str) -> None: ...


class NullMailer:
    """未配置 SMTP：不发信；注册流程据 enabled=False 自动验证。"""

    enabled = False

    async def send(self, to: str, subject: str, body: str) -> None:
        logger.debug("NullMailer 丢弃邮件 to=%s subject=%s", to, subject)


class RecordingMailer:
    """测试用：当作已配置的 Mailer，记录发送。"""

    enabled = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


class SmtpMailer:
    enabled = True

    def __init__(self, config: MailConfig) -> None:
        self._cfg = config

    def _send_sync(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self._cfg.sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(self._cfg.host, self._cfg.port, timeout=15) as smtp:
                if self._cfg.starttls:
                    smtp.starttls()
                if self._cfg.user:
                    smtp.login(self._cfg.user, self._cfg.password or "")
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"SMTP 发送失败：{type(exc).__name__}") from exc

    async def send(self, to: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, body)
