"""litellm 运行时依赖守卫（issue #31 / #44）。

litellm 1.92 的 completion() 会经 MCP/proxy 处理器惰性 import orjson，但 orjson
不是 litellm 基础安装的硬依赖——缺失时真实 LLM 调用在运行时炸
（ModuleNotFoundError: No module named 'orjson'）。env 门控的 smoke/bench 不在 CI
跑，无法覆盖此路径，故加此零网络守卫把 orjson 钉进依赖集。
"""


def test_orjson_available_for_litellm_completion_path() -> None:
    import orjson  # noqa: F401  # 缺失即 LiteLLMInstructorClient 真实调用会崩
