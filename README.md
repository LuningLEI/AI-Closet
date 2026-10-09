# AI Closet

AI Closet is a cross-platform wardrobe intelligence project with a Next.js web app, a Python FastAPI backend, Supabase Auth/Postgres/Storage, pgvector-backed vector storage, and an iOS app. The product goal is to turn a user's closet into structured, private style memory that can power upload recognition, outfit recommendation, and daily weather-aware styling.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `web/` | Next.js + TypeScript frontend for auth, closet management, profile preferences, recommendations, and today's outfit. |
| `backend/` | FastAPI API, recognition and outfit workers, model providers, persistence adapters, and experiment accounting. |
| `ios/` | Native iOS app and Core ML / outfit recommendation experiments. |
| `docs/` | Database and backend design guides, API contracts, and development runbooks. |

## Core Stack

- Frontend: Next.js, TypeScript
- Backend: Python, FastAPI
- AI workflow: vision recognition, embeddings, anchor-based outfit generation, and visual review
- Background processing: durable database queues with separate recognition and outfit workers
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

Install dependencies and configure the environment following [Local Development](docs/LOCAL_DEVELOPMENT.md). Apply the matching [database migrations](backend/sql/migrations/README.md) before starting the API and workers.

Run these from the repository root in separate terminals:

```bash
make backend-dev PYTHON=python
make worker PYTHON=python
# Outfit generation uses a separate worker:
cd backend && python -m app.outfit_worker
# Web client (another terminal, from the repository root):
make web-dev
```

Open `http://localhost:3000`.

## Manual Commands

Backend:

```bash
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Recognition worker:

```bash
cd backend
python -m app.worker
```

Outfit worker:

```bash
cd backend
python -m app.outfit_worker
```

Web:

```bash
cd web
npm run dev
```

## Documentation

Start here for a code-backed explanation of the design and interview discussion:

- [Database Design Guide — schema, technology choices, tradeoffs, and interview questions](docs/DATABASE_GUIDE.md)
- [Backend Architecture Guide — modules, workflows, technology choices, and limitations](docs/BACKEND_GUIDE.md)
- [Database Design Guide (Chinese)](docs/DATABASE_GUIDE.zh-CN.md)
- [Backend Architecture Guide (Chinese)](docs/BACKEND_GUIDE.zh-CN.md)
- [Data Architecture and Migration Guide (Chinese)](docs/DATA_ARCHITECTURE.zh-CN.md)

- [Architecture](docs/ARCHITECTURE.md)
- [API Contract](docs/API.md)
- [Local Development](docs/LOCAL_DEVELOPMENT.md)
- [Deployment Runbook](docs/DEPLOYMENT.md)
- [Contributing](CONTRIBUTING.md)

## Current Scope And Limitations

- Recognition runs asynchronously through a durable job table so uploads return before Vision and embedding work completes.
- The outfit library uses rule/vector candidate retrieval, model generation and visual review. The existing recommendation endpoints still use a separate deterministic candidate/scoring pipeline. Semantic embeddings are stored in pgvector; current per-user semantic ranking runs in the backend rather than database KNN retrieval.
- Personalization currently uses explicit preferences and filters. Human annotation and algorithm comparisons support evaluation; learning personalized behavior from interactions remains future work.
- Core database writes use transactions and version checks. External model calls, image storage, and frontend refreshes are outside that transaction boundary; retries do not guarantee exactly-once model execution.
- Model configuration is recorded per run, and usage is counted per model call. Missing pricing or usage remains unknown rather than being reported as free.
- Uploaded clothing photos are private in Supabase Storage. Recognition and image-enabled outfit generation/review send photos to the configured model provider. See the deployment guide before using real credentials or deploying the project.

## Security Notes

- Do not commit `.env`, `.env.local`, Supabase service-role keys, OpenAI keys, or signed storage URLs.
- Storage objects should live under user-scoped paths like `<user_id>/<object_id>.jpg`.
- Database access should remain scoped by `user_id` and protected by Supabase RLS policies.
