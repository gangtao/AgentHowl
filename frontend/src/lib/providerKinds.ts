// Provider 类型的展示名与默认地址——抄录自 backend/app/agent/provider.py
// （ProviderKind 字面量、DEFAULT_API_BASE、_PREFIX）。纯常量，零 IO。

import type { ProviderKind } from "../api/providers";

export const PROVIDER_KINDS: readonly ProviderKind[] = [
  "ollama",
  "openai",
  "anthropic",
  "openai_compatible",
  "gemini",
  "deepseek",
];

export const PROVIDER_KIND_ZH: Record<ProviderKind, string> = {
  ollama: "Ollama",
  openai: "OpenAI",
  anthropic: "Anthropic",
  openai_compatible: "OpenAI 兼容",
  gemini: "Gemini",
  deepseek: "DeepSeek",
};

/** 选中类型时自动填入的 API 地址；null = 留空（走 SDK 默认）。 */
export const DEFAULT_API_BASE: Record<ProviderKind, string | null> = {
  ollama: "http://localhost:11434",
  openai: null,
  anthropic: null,
  openai_compatible: null, // 必填
  gemini: null,
  deepseek: "https://api.deepseek.com",
};

/** LiteLLM 模型前缀（openai_compatible → openai）。 */
export const PROVIDER_PREFIX: Record<ProviderKind, string> = {
  ollama: "ollama",
  openai: "openai",
  anthropic: "anthropic",
  openai_compatible: "openai",
  gemini: "gemini",
  deepseek: "deepseek",
};

export const KIND_HINT: Record<ProviderKind, string> = {
  ollama: "Ollama 默认地址已自动填入；通常无需密钥。",
  openai: "地址留空走官方端点；密钥必填。",
  anthropic: "地址留空走官方端点；密钥必填。",
  openai_compatible: "OpenAI 兼容类型必须填写 API 地址。",
  gemini: "地址留空走官方端点；密钥必填。",
  deepseek: "已填入 DeepSeek 官方地址；密钥必填。",
};
