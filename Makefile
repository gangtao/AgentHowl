# AgentHowl 开发/测试/运行命令
#
# 所有 Python 命令经 uv 在 backend/ 下执行——无需手动 cd。
# 运行 `make` 或 `make help` 查看全部命令。
# 前端（frontend/）相关命令待 M3（issue #26）落地后补充。

BACKEND := backend
UV      := uv run

# 可调参数（示例：make watch SEED=3 VIEW=spectator /
#   make watch AI_MODEL=ollama/qwen2.5-coder:7b / make play SEAT=2 / make sim GAMES=100）
SEED     ?= 42
VIEW     ?= gm
SEAT     ?=
GAMES    ?= 1
AI_MODEL        ?=     # 设置后由 LLM Agent 自对局（如 ollama/qwen2.5-coder:7b）
AI_MODEL_SPEECH ?=     # 发言层单独模型（分层路由；缺省=同 AI_MODEL）
REFLECTION_MODEL ?=    # 每轮反思单独模型（通常更便宜；缺省=同 AI_MODEL）
THINKING        ?=     # 非空则开启推理模型思考（更强推理但慢；仅推理模型需要）
ARGS            ?=

# 由 AI_MODEL / *_MODEL / THINKING 组装的 LLM 相关命令行片段
_AIFLAGS := $(if $(AI_MODEL),--ai-model $(AI_MODEL),) \
	$(if $(AI_MODEL_SPEECH),--ai-model-speech $(AI_MODEL_SPEECH),) \
	$(if $(REFLECTION_MODEL),--reflection-model $(REFLECTION_MODEL),) \
	$(if $(THINKING),--thinking,)

.DEFAULT_GOAL := help

.PHONY: help
help: ## 显示所有可用命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ---- 依赖 ---------------------------------------------------------------

.PHONY: install
install: ## 安装/同步后端依赖（uv sync）
	cd $(BACKEND) && uv sync

# ---- 质量门 -------------------------------------------------------------

.PHONY: test
test: ## 跑全量测试（不含 smoke；约 140s）
	cd $(BACKEND) && $(UV) pytest -q

.PHONY: smoke
smoke: ## 跑真模型 smoke（需 AGENTHOWL_SMOKE_MODEL + 本地 Ollama）
	cd $(BACKEND) && $(UV) pytest -m smoke -q -s

.PHONY: lint
lint: ## ruff 静态检查
	cd $(BACKEND) && $(UV) ruff check .

.PHONY: format
format: ## ruff 自动格式化（改文件）
	cd $(BACKEND) && $(UV) ruff format .

.PHONY: format-check
format-check: ## ruff 格式检查（不改文件）
	cd $(BACKEND) && $(UV) ruff format --check .

.PHONY: typecheck
typecheck: ## mypy 严格类型检查
	cd $(BACKEND) && $(UV) mypy app

.PHONY: check
check: lint format-check typecheck test ## 全量质量门：lint + 格式 + 类型 + 测试

.PHONY: build
build: install check ## CI 式验证：装依赖 + 全量质量门（Python 应用无独立编译步骤）

# ---- 运行 ---------------------------------------------------------------

.PHONY: serve
serve: ## 启动 API 服务（uvicorn，热重载，http://localhost:8000）
	cd $(BACKEND) && $(UV) uvicorn app.main:app --reload

.PHONY: watch
watch: ## 终端看局（可选 SEED= VIEW=gm|spectator|seat:N AI_MODEL= THINKING=1 ARGS=）
	cd $(BACKEND) && $(UV) python -m app.cli.play --seed $(SEED) --view $(VIEW) $(_AIFLAGS) $(ARGS)

.PHONY: play
play: ## 终端玩局，你扮演 SEAT 座位（例：make play SEAT=2 AI_MODEL=ollama/qwen2.5-coder:7b）
	@test -n "$(SEAT)" || { echo "用法：make play SEAT=<座位号>  [AI_MODEL= THINKING=1 ARGS=]"; exit 2; }
	cd $(BACKEND) && $(UV) python -m app.cli.play --seat $(SEAT) $(_AIFLAGS) $(ARGS)

.PHONY: sim
sim: ## 纯引擎随机自对局胜负统计（例：make sim GAMES=100）
	cd $(BACKEND) && $(UV) python -m app.cli.simulate --games $(GAMES) $(ARGS)

# ---- 清理 ---------------------------------------------------------------

.PHONY: clean
clean: ## 清理缓存（__pycache__ / .pytest_cache / .mypy_cache / .ruff_cache）
	find $(BACKEND) -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache
