# Architecture

For a current code-reading and interview overview, see the [backend guide](BACKEND_GUIDE.md) and [database guide](DATABASE_GUIDE.md). Migration-dependent features require the corresponding SQL to be applied; source code presence does not confirm deployment.

AI Closet is split into three product surfaces: web, backend, and iOS. The backend owns data access, recognition, recommendations, storage signing, and user isolation. The web and iOS clients should share the same backend contracts wherever possible.

## High-Level Flow

```text
User
  -> Web / iOS client
  -> FastAPI backend
  -> Supabase Auth + Postgres + Storage
  -> OpenAI Vision / embeddings worker
  -> Recommendation services
```

## Upload And Recognition

1. Client sends an authenticated upload request.
2. Backend verifies the Supabase JWT and resolves `user_id`.
3. Image is stored in Supabase Storage under a user-scoped path.
4. A `clothing_items` row is created immediately so the UI can show a loading card.
5. A `recognition_jobs` row is queued.
6. Worker claims jobs, runs OpenAI Vision, normalizes taxonomy, generates embeddings, and writes:
   - `clothing_items`
   - `recognition_records`
   - `item_feature_snapshots`
7. UI refreshes/polls and replaces loading fields with final recognition results.

Recognition output is stored as typed fields plus auditable payloads:

- `clothing_items` keeps the latest item state for product UI and recommendation.
- `recognition_records` keeps each recognition/manual-edit event for model evaluation and debugging.
- `item_feature_snapshots` keeps vector and feature snapshots for retrieval and future ranking experiments.
- `item_edit_events` is an append-only log of user-confirmed card corrections, including taxonomy fields and final image transforms. It is analytics data, not the current item state.

Stable fields include version columns, taxonomy labels, material, pattern, fit, length, sleeve length, neckline, layering role, warmth level, formality score, confidence, and status. JSONB payloads remain available for raw provider output and backwards-compatible experiments.

## Recognition Queue Reliability

Recognition runs through a durable `recognition_jobs` queue instead of blocking the upload request.

- `queued`: job is waiting for a worker.
- `processing`: worker has claimed the job and set `leased_at`.
- `failed`: job failed but can be retried after `next_run_at`.
- `complete`: recognition finished and related tables were updated.
- `dead_letter`: job exceeded retry attempts or timed out too many times.

The worker supports:

- timeout recovery for stuck `processing` jobs
- exponential retry backoff
- max-attempt dead-lettering
- structured JSON logs
- queue health via `GET /api/v1/admin/queue/health`

Important environment knobs:

```text
RECOGNITION_WORKER_BATCH_SIZE=3
RECOGNITION_WORKER_POLL_SECONDS=2
RECOGNITION_WORKER_MAX_ATTEMPTS=3
RECOGNITION_WORKER_JOB_TIMEOUT_SECONDS=120
RECOGNITION_WORKER_RETRY_BASE_SECONDS=10
RECOGNITION_WORKER_RETRY_MAX_SECONDS=300
```

## Versioning

Backend schema, prompts, feature vectors, and profile memory use explicit version constants from `backend/app/core/versions.py`.

Current versions:

- `profile-v1`
- `taxonomy-v1`
- `style-preference-v1`
- `clothing-analysis-v1`
- `item-feature-v1`
- `taxonomy-normalization-v7-hosiery-layering`
- `manual-taxonomy-edit-v1`

These versions are stored with user preferences, clothing items, recognition records, and feature snapshots. This makes future migrations, model evaluation, and training dataset slicing easier because historical records can be grouped by the logic that created them.

## Observability

The FastAPI app adds a request id to every response through the `x-request-id` header. API requests and worker events are logged as structured JSON with event names, timestamps, latency, status codes, job ids, and user ids where relevant.

Core events include:

- `http.request`
- `http.request_failed`
- `recognition_worker.started`
- `recognition_worker.claimed`
- `recognition_worker.job_started`
- `recognition_worker.job_finished`
- `recognition_job.complete`
- `recognition_job.failed`

## Recommendation Flow

Recommendations combine:

- Closet item metadata
- User style preferences
- Selected/custom catalog taxonomy
- Weather context
- Semantic vectors from pgvector/OpenAI embeddings
- Outfit completeness and category compatibility rules

The current architecture supports both single-item recommendations and richer layered outfits later.

## Data Ownership

Every user-owned table includes `user_id` and is protected by Supabase Row Level Security:

- `clothing_items`
- `recognition_records`
- `item_feature_snapshots`
- `recognition_jobs`
- `item_edit_events`
- `user_preferences`

Storage objects are private and organized as:

```text
closet-images/<user_id>/<object_id>.jpg
```

The backend returns signed URLs instead of permanent public URLs.

## Profile And Preference Model

`user_preferences` is intentionally split into typed columns plus an extensible JSONB memory document.

Typed columns are used for values that should be queryable, validated, and useful for future recommendation training:

- `profile_version`, `taxonomy_version`, `style_preference_version`
- `onboarding_completed`
- `nickname`, `avatar_path`, `birth_year`, `gender_identity`
- `daily_occasions`, `style_preferences`
- `selected_categories`, `custom_categories`
- `model_training_consent`
- `profile_features`

The `preferences` JSONB column is still kept as a compatibility and extension layer. The backend normalizes every read/write so the typed columns and JSON memory stay aligned. This lets web and iOS use a stable API while preserving flexibility for new profile questions, experiments, and model features.

## Cross-Platform Contract

The iOS app should reuse backend concepts rather than creating a separate data model:

- User identity from Supabase Auth
- Closet items from `clothing_items`
- Profile preferences from `user_preferences`
- Upload recognition through FastAPI
- Recommendations from the shared backend engine

The API contract is exported from FastAPI OpenAPI into `docs/api/openapi.json`. Web TypeScript types are generated from that contract into `web/lib/generated/api-types.ts`; iOS can later generate a Swift client from the same file.

## Anchor-driven outfit library

`app/outfits/` implements a separately configured two-pass image generation/evaluation pipeline. `outfit_libraries` enrolls users, `outfit_build_jobs` persists leased idempotent anchor jobs, `outfits` retains immutable versioned scores and item snapshots, and `outfit_items` indexes membership. Owner-read RLS and service-role-only claim/save RPCs protect model-generated state. Local development uses transactional SQLite through the same store interface.

The outfit worker polls ready clothing records for enrolled users and adds jobs for new item or inference revisions. The API filters versioned results by current member state, structure and configured aesthetic cutoff; threshold-only changes reuse saved scores. iOS Closet switches between Items and Outfits and supports querying every accepted outfit containing a selected item. The existing weather/occasion recommender remains unchanged until a later library-ranking phase. See `backend/app/outfits/README.md` for configuration and operational details.

## Data lifecycle and outfit runs (008 / 009)

See [数据架构与技术说明](DATA_ARCHITECTURE.zh-CN.md) for table ownership, current-versus-history
relationships, atomic RPC boundaries, per-call accounting, retention, and rollout instructions.
Run manifests are immutable; detailed model-call usage is counted once per request, not once per
outfit. Missing billing data remains unknown. Current evaluation membership is derived from
`outfit_projection_sources`; raw model evidence remains JSON while indexed review columns are
database-generated. Production changes require sequential migrations 008 and 009 and a read-model
rebuild before the API/workers restart. Legacy audit rows are preserved without invented run costs.
