# LinguisPlay

Contract-first monorepo for the LinguisPlay MVP (rewrite of the `/opt/persona` demo backend).

```
linguisplay/
├── packages/contract/      # openapi.yaml v0 — single source of truth, FE+BE both follow it
├── apps/api/               # FastAPI + Postgres + pgvector + SQLAlchemy
└── apps/web/               # Vite + React + TS (SSE chat, gated UI)
```

## Milestones

- **M0** — monorepo + frozen `openapi.yaml v0` + Hollow Vale seed *(done / in progress)*
- **M1** — `apps/api` skeleton: Auth, /me, /personas, /stories CRUD (no gating) ← **you are here**
- **M2** — gated RAG engine (unlock_schema) + 小手机 side-effects — the differentiator
- **M3** — real LLM + SSE + compliance + Stripe
- **M4** — closed beta, cut over from old demo

## Quick start (M1)

```bash
# 1. infra
docker compose up -d            # Postgres(+pgvector) on :5432, Redis on :6379

# 2. api
cd apps/api
cp .env.example .env
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
uvicorn app.main:app --reload   # http://localhost:8000/docs

# 3. web
cd apps/web
npm install
npm run dev                      # http://localhost:5173
```

API docs (Swagger) at `/docs`. Health at `/api/v1/health`.
