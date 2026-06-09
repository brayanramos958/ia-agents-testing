# AGENTS.md

## Repo shape
- This git repo is a container for **independent projects** (`ia-agent-tickets-v1/`, `ia-agent-tickets-v2/`, `projects-machine/`). There is **no shared root build/test command**. Work inside the target project directory.
- For the current helpdesk work, the active code is `ia-agent-tickets-v2/`.

## Highest-value sources
- `ia-agent-tickets-v2/agent/agent-v2/CLAUDE.md` is the local operator guide, but it is **partly stale**: current code already supports JWT auth and optional HTTPS. For auth/runtime behavior, trust `main.py`, `api/routes/auth.py`, and `api/middleware/jwt_auth.py` over curl examples in docs.
- `ia-agent-tickets-v2/agent/agent-v2/config/settings.py` is the single source of truth for runtime config.

## ia-agent-tickets-v2 architecture
- `backend/` = local dev backend (FastAPI + SQLite).
- `agent/agent-v2/` = real agent service (FastAPI + LangGraph + pgvector + PostgreSQL checkpointer).
- The agent chooses its backend via `BACKEND_ADAPTER` in env:
  - `express` = local dev adapter.
  - `odoo` = production adapter.
  - `http` = legacy/deprecated.
- `main.py` wires the app in lifespan order: build ticket adapter → build/seed RAG → init checkpointer → inject ports into tools.

## Verified commands
- Start the local dev backend:
  - `cd ia-agent-tickets-v2/backend`
  - `source venv/bin/activate`
  - `python populate_db.py`  # first time only
  - `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
- Start the agent dev stack with hot reload:
  - `cd ia-agent-tickets-v2/agent/agent-v2`
  - `bash docker-up-dev.sh`
- Stop the dev stack:
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml down`
- Focused verification:
  - `curl http://localhost:8001/health`
  - `uv run python scratch/test_sara.py creador --port 8001 --delay 3 --verbose`
  - `bash /home/bramos01/Documentos/ia-agents/ia-agent-tickets-v2/test_prompts.sh`

## Runtime quirks that are easy to miss
- In Docker dev, `docker-compose.dev.yml` runs `uv sync --no-dev` at container start. **After editing `pyproject.toml`, restart the container; do not rebuild just for dependency changes.**
- `docker-up-dev.sh` detects `DOCKER_HOST_IP` for WSL2/Linux host resolution. If backend calls fail from the container, inspect that script and `extra_hosts` in `docker-compose.yml` before changing application code.
- `main.py` calls `load_dotenv()` before importing settings. Local non-Docker runs depend on `.env`; Docker runs depend on `env.docker` via Compose.
- `env.docker` defaults to `BACKEND_ADAPTER=express` and `BACKEND_URL=http://host.docker.internal:8000`. If you switch to Odoo, update env first; do not debug the Express path by accident.

## Auth and transport
- Production auth is now `Authorization: Bearer <jwt>` via `/auth/login`; `X-Agent-Key` is still accepted as a dev/backward-compatible fallback.
- Protected agent routes also validate that request body `user_id`/`user_rol` match JWT claims. If chat/invoke/stream returns 403, inspect the body/token mismatch before touching role logic.
- If `/app/certs/cert.pem` and `/app/certs/key.pem` exist, `main.py` starts uvicorn on **8443** with SSL; otherwise it serves HTTP on `settings.port` (default `8001`).
- `docker-compose.yml` healthcheck still probes `http://localhost:8001/health`. If certs are mounted and the app is HTTPS-only, healthcheck behavior can mislead you.

## Repo-specific guardrails
- Use **`uv`** for `agent/agent-v2` dependency management. The Dockerfile installs only `uv` with pip, then uses `uv sync --frozen --no-dev`.
- Root `.gitignore` intentionally tracks `env.docker` / `env.example`. **Do not put secrets in tracked env files.**
- Generated files currently show up in git status and should not be committed by accident:
  - `ia-agent-tickets-v2/agent/agent-v2/.build-timestamp`
  - `ia-agent-tickets-v2/backend/helpdesk.db-journal`
  - `ia-agent-tickets-v2/agent/agent-v2/certs/`
- `ITS_Helpdesk_Docst_no_editable/` and `documents_api_Production/` are excluded in root `.gitignore`; do not plan changes there as part of normal agent work.
