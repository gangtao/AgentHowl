"""邮件配置与 Mailer（issue #114）。"""

import pytest

from app.runtime.mailer import MailConfig, NullMailer, RecordingMailer


def test_from_env_none_when_no_host() -> None:
    assert MailConfig.from_env({}) is None
    assert MailConfig.from_env({"AGENTHOWL_SMTP_HOST": "  "}) is None


def test_from_env_requires_from() -> None:
    with pytest.raises(ValueError):
        MailConfig.from_env({"AGENTHOWL_SMTP_HOST": "smtp.x"})


def test_from_env_full() -> None:
    cfg = MailConfig.from_env(
        {
            "AGENTHOWL_SMTP_HOST": "smtp.x",
            "AGENTHOWL_SMTP_PORT": "2525",
            "AGENTHOWL_SMTP_USER": "u",
            "AGENTHOWL_SMTP_PASSWORD": "p",
            "AGENTHOWL_SMTP_FROM": "noreply@x",
            "AGENTHOWL_SMTP_STARTTLS": "0",
        }
    )
    assert cfg is not None
    assert (cfg.host, cfg.port, cfg.user, cfg.sender, cfg.starttls) == (
        "smtp.x",
        2525,
        "u",
        "noreply@x",
        False,
    )
    assert "password" not in repr(cfg) and "'p'" not in repr(cfg)


@pytest.mark.asyncio
async def test_null_and_recording() -> None:
    null = NullMailer()
    assert null.enabled is False
    await null.send("a@x", "s", "b")
    rec = RecordingMailer()
    assert rec.enabled is True
    await rec.send("a@x", "s", "b")
    assert rec.sent == [("a@x", "s", "b")]
