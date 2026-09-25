// 模型服务 Provider 端点薄封装（对应 backend/app/api/providers.py，规格 §2c/§6）。

import { req } from "./rest";

export type ProviderKind =
  | "ollama"
  | "openai"
  | "anthropic"
  | "openai_compatible"
  | "gemini"
  | "deepseek";

/** API 响应：永不含 api_key（对应 ProviderPublic）。 */
export interface ProviderPublic {
  provider_id: string;
  name: string;
  kind: ProviderKind;
  api_base: string | null;
  has_key: boolean;
  key_hint: string | null;
  default_model: string | null;
  created_at: string;
  updated_at: string;
}

/** POST/PUT 请求体（对应 ProviderInput）：PUT 省略 api_key = 保留原密钥，"" = 清除。 */
export interface ProviderInput {
  name: string;
  kind: ProviderKind;
  api_base?: string | null;
  api_key?: string;
  default_model?: string | null;
}

export interface ProviderTestResult {
  ok: boolean;
  latency_ms: number | null;
  error?: string | null;
}

export interface ProviderModelsResult {
  models: string[];
  error?: string | null;
}

export function listProviders(): Promise<ProviderPublic[]> {
  return req<ProviderPublic[]>("GET", "/providers");
}

export function createProvider(body: ProviderInput): Promise<ProviderPublic> {
  return req<ProviderPublic>("POST", "/providers", { body });
}

export function getProvider(providerId: string): Promise<ProviderPublic> {
  return req<ProviderPublic>("GET", `/providers/${providerId}`);
}

export function updateProvider(providerId: string, body: ProviderInput): Promise<ProviderPublic> {
  return req<ProviderPublic>("PUT", `/providers/${providerId}`, { body });
}

export function deleteProvider(providerId: string): Promise<void> {
  return req<void>("DELETE", `/providers/${providerId}`);
}

export function testProvider(providerId: string, model?: string): Promise<ProviderTestResult> {
  return req<ProviderTestResult>("POST", `/providers/${providerId}/test`, {
    body: model ? { model } : {},
  });
}

export function listModels(providerId: string): Promise<ProviderModelsResult> {
  return req<ProviderModelsResult>("GET", `/providers/${providerId}/models`);
}
