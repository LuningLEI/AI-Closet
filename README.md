# AI Closet

AI Closet is a cross-platform wardrobe intelligence project with a Next.js web app, a Python FastAPI backend, Supabase Auth/Postgres/Storage, pgvector-backed vector storage, and an iOS app. The product goal is to turn a user's closet into structured, private style memory that can power upload recognition, outfit recommendation, and daily weather-aware styling.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `web/` | Next.js + TypeScript frontend for auth, closet management, profile preferences, recommendations, and today's outfit. |
| `backend/` | FastAPI API, recognition queue worker, OpenAI vision/embedding pipeline, Supabase repository layer, and recommendation services. |
| `ios/` | Native iOS app and Core ML / outfit recommendation experiments. |
| `docs/` | Architecture and local development runbooks for collaborators. |

## Core Stack

- Frontend: Next.js, TypeScript
- Backend: Python, FastAPI
- AI/Agent workflow: OpenAI Vision, embeddings, async recognition worker
- Database: Supabase Postgres with pgvector-backed item embeddings
- Storage: Supabase Storage with private user-scoped object paths and signed URLs
- Auth and security: Supabase Auth, Row Level Security, user-owned records
- Deployment targets: Vercel for web, Render/Railway for backend workers

## Local Start

The bundled Core ML model is stored with Git LFS. Before building iOS from a fresh clone:

```bash
git lfs install
git lfs pull
```

Run these in separate terminals:

```bash
make backend-dev
make worker
make web-dev
```

Open `http://localhost:3000`.

## Manual Commands

Backend:

```bash
cd backend
/opt/anaconda3/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Worker:

```bash
cd backend
/opt/anaconda3/bin/python -m app.worker
```

Web:

```bash
cd web
npm run dev
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [API Contract](docs/API.md)
- [Local Development](docs/LOCAL_DEVELOPMENT.md)
- [Deployment Runbook](docs/DEPLOYMENT.md)
- [Contributing](CONTRIBUTING.md)

## Current Scope And Limitations

- Recognition runs asynchronously through a durable job table so uploads return before Vision and embedding work completes.
- Outfit selection uses deterministic candidate generation and explainable scoring. Semantic embeddings are stored in pgvector, while the current MVP performs per-user semantic re-ranking in the backend rather than database KNN retrieval.
- Personalization currently comes from explicit profile preferences and current filters. Interaction-based learning and offline ranking evaluation are planned, not yet implemented.
- Uploaded clothing photos are private in Supabase Storage and are sent to OpenAI Vision only for the user-requested recognition step. See the deployment guide before using real credentials or deploying the project.

## Security Notes

- Do not commit `.env`, `.env.local`, Supabase service-role keys, OpenAI keys, or signed storage URLs.
- Storage objects should live under user-scoped paths like `<user_id>/<object_id>.jpg`.
- Database access should remain scoped by `user_id` and protected by Supabase RLS policies.
