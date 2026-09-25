"""模型服务 Provider（issue #26）：地址 / 密钥 / 默认模型；纯 pydantic。

kind 即 LiteLLM 模型前缀（openai_compatible → "openai" 前缀 + 自定义 api_base）。
凭据在 build_agent_port 时绑定到该端口的 LiteLLMInstructorClient，不进 AgentConfig / 事件日志。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ProviderKind = Literal["ollama", "openai", "anthropic", "openai_compatible", "gemini", "deepseek"]

_PREFIX: dict[str, str] = {
    "ollama": "ollama",
    "openai": "openai",
    "anthropic": "anthropic",
    "openai_compatible": "openai",
    "gemini": "gemini",
    "deepseek": "deepseek",
}
DEFAULT_API_BASE: dict[str, str | None] = {
    "ollama": "http://localhost:11434",
    "openai": None,
    "anthropic": None,
    "openai_compatible": None,  # 必填
    "gemini": None,
    "deepseek": "https://api.deepseek.com",
}


class ProviderInput(BaseModel):
    """POST/PUT 请求体；PUT 时 api_key 省略 = 保留原密钥、"" = 清除。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: ProviderKind
    api_base: str | None = None
    api_key: str | None = None
    default_model: str | None = None

    @model_validator(mode="after")
    def _fill_and_check(self) -> ProviderInput:
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name 不能为空")
        if self.api_base is None:
            self.api_base = DEFAULT_API_BASE[self.kind]
        if self.kind == "openai_compatible" and not self.api_base:
            raise ValueError("openai_compatible 类型须填写 api_base")
        return self


class Provider(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_id: str
    name: str
    kind: ProviderKind
    api_base: str | None
    # repr=False：日志/异常里裸打印 Provider（如 f"{provider!r}"）不会带出明文密钥；
    # 不影响 model_dump_json（落盘仍完整持久化，见 provider_store 的 0600 权限约束）。
    api_key: str | None = Field(default=None, repr=False)
    default_model: str | None
    created_at: str
    updated_at: str


class ProviderPublic(BaseModel):
    """API 响应：永不含 api_key。"""

    provider_id: str
    name: str
    kind: ProviderKind
    api_base: str | None
    has_key: bool
    key_hint: str | None
    default_model: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_provider(cls, p: Provider) -> ProviderPublic:
        # 短密钥（≤4 字符）不给提示：后 4 位即整串，等于把密钥原样回显
        key_hint = p.api_key[-4:] if p.api_key and len(p.api_key) > 4 else None
        return cls(
            provider_id=p.provider_id,
            name=p.name,
            kind=p.kind,
            api_base=p.api_base,
            has_key=bool(p.api_key),
            key_hint=key_hint,
            default_model=p.default_model,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )


def resolve_model(model: str, provider: Provider | None) -> str:
    """provider 为空 → 原样（含前缀、走环境变量）；否则拼 LiteLLM 前缀。"""
    if provider is None:
        return model
    return f"{_PREFIX[provider.kind]}/{model}"


def redact_secret(text: str, key: str | None) -> str:
    """把明文密钥从文本里原样替换成 "****"（纯函数，无 IO）。

    探测器（provider_probe）与 API 端点均调用此函数做脱敏，端点侧是纵深防御：
    即便探测器实现忘了脱敏，响应出口也兜底。
    """
    if not key:
        return text
    return text.replace(key, "****")
