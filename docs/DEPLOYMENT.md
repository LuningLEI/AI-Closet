# Deployment Runbook

AI Closet deploys as three production components:

- Web: Next.js on Vercel
- Backend API: FastAPI on Render or Railway
- Recognition worker: long-running Python worker on Render or Railway

Supabase owns Auth, Postgres, pgvector, Row Level Security, and private Storage.

## Pre-Deploy Checklist

Before deploying, confirm:

- `backend/sql/schema.sql` has been applied in Supabase SQL Editor.
- `closet-images` exists in Supabase Storage.
- Storage bucket is private.
- RLS policies are enabled for user-owned tables.
- `make api-contract` has been run after API model changes.
- `make backend-test`
- `make backend-check`
- `make web-build`

## Backend On Render

This repo includes a Render blueprint:

```text
render.yaml
```

It defines:

- `ai-closet-api`: FastAPI web service
- `ai-closet-recognition-worker`: background recognition worker

The API service starts with:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

The worker starts with:

```bash
python -m app.worker
```

## Backend Environment Variables

Set these for both API and worker:

```text
APP_ENV=production
APP_NAME=AI Closet API
WEB_ORIGIN=https://your-vercel-domain.vercel.app
STORAGE_MODE=supabase
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_KEY=your-publishable-or-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_STORAGE_BUCKET=closet-images
OPENAI_API_KEY=your-openai-api-key
OPENAI_VISION_MODEL=gpt-4.1-mini
OPENAI_VISION_DETAIL=low
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_EMBEDDING_DIMENSIONS=1536
RECOGNITION_WORKER_BATCH_SIZE=3
RECOGNITION_WORKER_POLL_SECONDS=2
RECOGNITION_WORKER_MAX_ATTEMPTS=3
RECOGNITION_WORKER_JOB_TIMEOUT_SECONDS=120
RECOGNITION_WORKER_RETRY_BASE_SECONDS=10
RECOGNITION_WORKER_RETRY_MAX_SECONDS=300
REQUIRE_AUTH_FOR_MUTATIONS=true
```

Do not expose `SUPABASE_SERVICE_ROLE_KEY` to the web client.

## Web On Vercel

Set Vercel project root to:

```text
web
```

Build command:

```bash
npm run build
```

Install command:

```bash
npm install
```

Vercel environment variables:

```text
NEXT_PUBLIC_API_BASE_URL=https://your-api-service.onrender.com
NEXT_PUBLIC_SUPABASE_URL=https://your-project-ref.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-supabase-publishable-or-anon-key
```

After Vercel deploys, update backend `WEB_ORIGIN` to the Vercel production URL.

## Health Checks

API health:

```http
GET /api/v1/health
```

Expected response:

```json
{"status":"ok"}
```

Root metadata:

```http
GET /
```

Expected response:

```json
{"name":"AI Closet API","env":"production"}
```

Recognition queue health:

```http
GET /api/v1/admin/queue/health
Authorization: Bearer <supabase-jwt>
```

Use this when uploads create closet cards but recognition does not complete.

## Logs And Request Tracing

The backend emits structured JSON logs. Every API response includes:

```text
x-request-id: <uuid>
```

Send the same header from a client or API debugger to trace a request across logs:

```http
x-request-id: local-debug-001
```

Important log fields:

- `event`: event name such as `http.request` or `recognition_job.failed`
- `timestamp`: UTC ISO timestamp
- `request_id`: request correlation id for HTTP requests
- `method`, `path`, `status_code`, `elapsed_ms`: API request diagnostics
- `job_id`, `user_id`, `attempts`, `elapsed_ms`: worker diagnostics
- `error`: exception type or failure reason

## Production Operations

When uploads work but cards stay in `Analyzing`:

1. Check worker service is running.
2. Call `/api/v1/admin/queue/health`.
3. Inspect `status_counts`, `dead_letter_jobs`, and `recent_errors`.
4. Check OpenAI and Supabase keys in the worker environment.
5. Restart the worker if jobs are stuck in `processing` beyond the timeout.

When images do not render:

1. Confirm `closet-images` is private.
2. Confirm storage object paths start with `<user_id>/`.
3. Confirm backend has `SUPABASE_SERVICE_ROLE_KEY`.
4. Confirm the API returns signed URLs, not permanent public URLs.

When login works but API requests return 401:

1. Confirm web uses the same Supabase project as backend.
2. Confirm `NEXT_PUBLIC_SUPABASE_URL` matches backend `SUPABASE_URL`.
3. Confirm browser requests include `Authorization: Bearer <token>`.
4. Confirm backend `WEB_ORIGIN` matches Vercel URL.

When schema changes:

1. Prefer applying the next numbered migration in `backend/sql/migrations/`.
2. Keep `backend/sql/schema.sql` as the full fresh-environment snapshot.
3. Apply `backend/sql/schema.sql` only for fresh environments or when intentionally resyncing the snapshot.
4. Run `make api-contract` if API contracts changed.
5. Redeploy backend API, worker, and web if contracts changed.

## Railway Notes

Railway can use the same process commands:

API:

```bash
cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Worker:

```bash
cd backend && python -m app.worker
```

Use separate Railway services so the worker can restart independently from the API.
