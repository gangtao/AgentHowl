"""Provider 模型与存储（issue #26）：resolve_model、公开视图不含密钥、文件 0600、坏文件。"""

import os

from app.agent.provider import Provider, ProviderPublic, resolve_model
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
