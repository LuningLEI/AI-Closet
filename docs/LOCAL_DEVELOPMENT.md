# Local Development

## Prerequisites

- Python available at `/opt/anaconda3/bin/python` or set `PYTHON=/path/to/python`
- Node.js and npm
- Supabase project with Auth, Postgres, pgvector, and Storage
- OpenAI API key for recognition and embeddings

## Environment Files

Backend:

```bash
cp backend/.env.example backend/.env
```

Web:

```bash
cp web/.env.example web/.env.local
```

Keep real values local. Do not commit `.env` or `.env.local`.

## Database

Apply the schema in:

```text
backend/sql/schema.sql
```

`backend/sql/schema.sql` is the full idempotent snapshot. Numbered migration files live in:

```text
backend/sql/migrations/
```

Use migrations to review schema history; use the full snapshot for a fresh Supabase project.

The schema enables:

- `pgcrypto`
- `vector`
- user-owned closet tables
- recognition queue table
- user preferences
- Row Level Security policies
- private Supabase Storage object policies

## Start The Project

Use three terminals.

Terminal 1, backend API:

```bash
make backend-dev
```

Terminal 2, recognition worker:

```bash
make worker
```

The worker processes `recognition_jobs`, retries failed jobs with backoff, times out stuck jobs, and moves exhausted jobs into `dead_letter`.

Terminal 3, web app:

```bash
make web-dev
```

Then open:

```text
http://localhost:3000
```

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

## Checks

```bash
make backend-check
make backend-test
make web-build
```

GitHub Actions runs the same backend tests, backend compile check, API contract generation check, and web build on pushes and pull requests.

## API Contract

When backend request or response models change, regenerate the shared API contract:

```bash
make api-contract
```

This updates `docs/api/openapi.json` and `web/lib/generated/api-types.ts`.

## Common Issues

- If `cd web` fails, check that you are at the project root, not inside `backend/`.
- If uploads create loading cards but recognition does not finish, start the worker.
- If weather or Supabase calls fail, verify `.env` and `.env.local`.
- If Supabase shows the project as paused, resume it from the Supabase dashboard.
- If Next.js reports missing chunks, stop the web server and remove stale `.next` output.
