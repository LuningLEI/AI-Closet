# AI Closet

AI Closet is an iOS wardrobe intelligence system backed by FastAPI, PostgreSQL/Supabase, pgvector, durable workers, and a per-user Taste Profile. Image upload is independent from recognition; outfit generation, visual review, feedback reduction, and recommendation ranking run through versioned background workflows.

## Repository layout

| Path | Responsibility |
|---|---|
| `ios/` | SwiftUI client and presentation state |
| `backend/app/` | API, domain services, repositories, recommendation policy, and provider-neutral AI interfaces |
| `backend/workers/` | Recognition, outfit, Taste Profile, and feedback-summary entry points |
| `backend/tools/admin/` | Repair, inspection, and backfill commands |
| `backend/tools/evaluation/` | Offline evaluation, simulation, annotation, and export tools |
| `backend/sql/` | Schema, migrations, RLS, RPCs, and SQL regression tests |
| `evaluation/` | Human annotation and reproducible evaluation artifacts |

The backend owns the taxonomy. iOS downloads `/api/v1/taxonomy`; no client-side default catalog is maintained.

## Production flow

1. iOS uploads an image and receives a durable recognition job.
2. The recognition worker reads the user's current taxonomy, calls the AI Gateway, normalizes output, computes vectors, and commits with lease/version checks.
3. The outfit worker builds clothing-first candidates, selects shoes/accessories in a batched stage, applies deterministic rules, and performs visual review.
4. Outfit feedback is appended as evidence. The deterministic Taste Profile reducer creates a versioned per-user profile.
5. Today and Recommendations both call `PersonalizedRecommendationService`; only their initial context differs. They rank the same projection using preferences, Taste Profile, wear recency, and controlled exploration.

## Local commands

```bash
cp backend/.env.example backend/.env
make backend-dev
make worker
make outfit-worker
make taste-profile-worker
make free-text-taste-worker
```

Quality checks:

```bash
python -m pip install -r backend/requirements-dev.lock
make check PYTHON=python
make api-contract PYTHON=python
xcodebuild -project "ios/AI Closet.xcodeproj" -scheme "AI Closet" \
  -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build
```

Run `make clean` to remove local Python caches and Xcode build products. It
preserves wardrobe images, evaluation artifacts, and model packages.

`backend/pyproject.toml` declares dependency intent. Lock files contain the tested production and development resolutions. Runtime model calls use `AI_PROVIDER`, `AI_BASE_URL`, and `AI_API_KEY`, so an OpenAI-compatible provider can replace OpenAI without changing domain services.

## Reliability and privacy

- Supabase RLS and user-scoped repositories isolate user data.
- Jobs use leases, retries, version checks, idempotent identifiers, and stale-job rejection.
- Outfit runs store model/prompt hashes, usage, cost, and a unified runtime configuration snapshot.
- Structured logs carry request IDs; readiness, queue health, and internal counters support operations.
- Feedback is append-only evidence. Model output is never treated as a user label.
- Cross-user learning is disabled unless a user explicitly consents.

Use the [documentation index](docs/README.md) to navigate architecture, product,
evaluation, and operations material. Direct entry points include
[Architecture](docs/architecture/system.md), [Database guide](docs/architecture/database.md),
and [Deployment](docs/operations/deployment.md).
