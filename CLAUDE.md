# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AgentHowl is a multi-agent Werewolf (狼人杀) game platform where every seat can be an LLM agent or a human, connected through one unified player API. The authoritative design is the spec at `docs/specs/requirements.md` (Chinese PRD + technical design) — read the relevant section before implementing any feature; it defines the GameConfig schema, phase state machine, role timings, agent tool schemas, API contracts, and milestones. Current focus: **M1 — the rule engine core**.

## Stack and tooling

- Backend: Python 3.11+, FastAPI + Uvicorn, Pydantic v2, `python-statemachine`, LiteLLM + `instructor` for the model-agnostic LLM layer. Managed with **uv** (`uv add`, `uv run pytest`).
- Lint/type-check (run from `backend/`): `uv run ruff check .`, `uv run ruff format .`, `uv run mypy app` (mypy is strict mode).
- Frontend: React 18 + TypeScript + Vite.
- Planned layout: `backend/` + `frontend/` + `docs/` (see spec §6.2 for the backend module breakdown).

## Hard architectural constraints (from spec §1.3)

- The game engine (`backend/app/engine/`) is **pure functions with zero IO**: `step(state, action) -> (new_state, events)`. It must not import network, DB, or LLM code. IO lives in `backend/app/runtime/`.
- Every state change is an append-only Event; state = `reduce(events)`. The frontend implements a matching TypeScript `reduce()` so live view and replay share one reducer.
- The server is the single source of truth — clients and agents submit intents only, never self-adjudicate.
- Information isolation is a **server-side** security boundary. The frontend does no filtering; it only renders what the server sends per view.
- All randomness goes through one seeded RNG (`GameConfig.seed`) so deals and tie-breaks are reproducible.
- No game rule is hardcoded — every rule variant is a `GameConfig` toggle.

## Game-logic gotchas (spec §5)

- Night action windows may open in parallel but must resolve serially per `night_order` (e.g. the witch must see the wolves' kill before acting).
- Wolf-kill-first: if wolves meet the win condition at night, the game ends immediately — later witch-poison / hunter-shot are void.
- Wolf private chat and public speech must use separate LLM calls so private reasoning never leaks.

## Conventions

- Docs and code comments: Chinese prose; code identifiers, API names, and schemas: English.
- Determinism tests use a fixed `GameConfig.seed`; rule-engine tests must not require any IO or mocking.
