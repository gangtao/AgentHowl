"""Provider 模型与存储（issue #26）：resolve_model、公开视图不含密钥、文件 0600、坏文件。"""

import os

from app.agent.provider import Provider, ProviderPublic, resolve_model
from app.runtime.provider_probe import _redact
from app.runtime.provider_store import InMemoryProviderStore, JsonFileProviderStore


def _p(**kw: object) -> Provider:
    base = {
        "provider_id": "p_00000001",
        "name": "本地 Ollama",
        "kind": "ollama",
        "api_base": "http://localhost:11434",
        "api_key": None,
        "default_model": "qwen2.5:14b",
        "created_at": "t",
        "updated_at": "t",
    }
    base.update(kw)
    return Provider.model_validate(base)


def test_resolve_model_prefix_and_compat_mode() -> None:
    assert resolve_model("ollama/x", None) == "ollama/x"  # provider 为空：原样（走环境变量）
    assert resolve_model("qwen2.5:14b", _p()) == "ollama/qwen2.5:14b"
    assert resolve_model("gpt-4o-mini", _p(kind="openai", api_base=None)) == "openai/gpt-4o-mini"
    compat = _p(kind="openai_compatible", api_base="https://llm/v1")
    assert resolve_model("qwen-max", compat) == "openai/qwen-max"
    assert resolve_model("claude-3-5-haiku", _p(kind="anthropic")) == "anthropic/claude-3-5-haiku"


def test_public_view_hides_key() -> None:
    pub = ProviderPublic.from_provider(_p(api_key="sk-abcdefgh1234"))
    d = pub.model_dump()
    assert "api_key" not in d and d["has_key"] is True and d["key_hint"] == "1234"
    assert ProviderPublic.from_provider(_p()).key_hint is None


def test_public_view_short_key_gets_no_hint() -> None:
    """密钥长度 ≤4 时后 4 位即整串，不给提示，避免把短密钥原样回显。"""
    short = ProviderPublic.from_provider(_p(api_key="abc"))
    assert short.has_key is True and short.key_hint is None
    long_ = ProviderPublic.from_provider(_p(api_key="sk-12345678"))
    assert long_.has_key is True and long_.key_hint == "5678"


def test_provider_repr_never_leaks_key() -> None:
    provider = _p(api_key="sk-topsecret")
    assert "sk-topsecret" not in repr(provider) and "sk-topsecret" not in str(provider)
    # repr(Provider) 不含密钥不代表落盘不含：model_dump_json 仍完整持久化
    assert "sk-topsecret" in provider.model_dump_json()


def test_store_roundtrip_mode_and_corruption(tmp_path, caplog) -> None:
    d = tmp_path / "providers"
    store = JsonFileProviderStore(d)
    assert store.list() == [] and not d.exists()
    store.put(_p(api_key="sk-secret"))
    path = d / "p_00000001.json"
    assert path.exists() and (path.stat().st_mode & 0o777) == 0o600
    assert "sk-secret" in path.read_text(encoding="utf-8")  # 本地明文，权限 0600（README 明示）
    got = JsonFileProviderStore(d).get("p_00000001")
    assert got is not None and got.api_key == "sk-secret"
    (d / "p_bad.json").write_text("{", encoding="utf-8")
    assert [p.provider_id for p in JsonFileProviderStore(d).list()] == ["p_00000001"]
    assert "p_bad.json" in caplog.text
    mem = InMemoryProviderStore()
    mem.put(_p())
    assert mem.get("p_00000001") is not None
    assert mem.delete("p_00000001") and not mem.delete("p_00000001")
    os.chmod(path, 0o600)


def test_redact_strips_api_key_from_probe_error_messages() -> None:
    msg = "AuthenticationError: invalid key sk-topsecret for request"
    assert _redact(msg, "sk-topsecret") == "AuthenticationError: invalid key **** for request"
    assert _redact(msg, None) == msg  # 无密钥：原样返回
    assert _redact(msg, "") == msg  # 空串：原样返回（避免 "" in msg 恒真的误替换）
    assert _redact("no secret here", "sk-topsecret") == "no secret here"  # 不含密钥：原样
