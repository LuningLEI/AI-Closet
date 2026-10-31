# Deployment

`render.yaml` defines the FastAPI service and four independently scalable workers: recognition, outfit generation, Taste Profile reduction, and low-frequency feedback summarization.

Before deployment:

1. Apply ordered SQL migrations to Supabase and run SQL regressions on a disposable database.
2. Set Supabase server credentials, storage bucket, `AI_PROVIDER`, `AI_BASE_URL`, and `AI_API_KEY`.
3. Keep `REQUIRE_AUTH_FOR_MUTATIONS=true`; set `ALLOWED_ORIGINS` only for a trusted additional client.
4. Run tests, lint, type checks, OpenAPI drift, migration validation, and the iOS build through CI.
5. Deploy API and workers from the same Git commit so runtime snapshots describe one release.

Production signals:

- `/api/v1/health`: liveness
- `/api/v1/ready`: readiness and configuration hash
- `/api/v1/admin/queue/health`: queue backlog and dead letters
- `/api/v1/admin/metrics`: internal counters protected by `X-Observability-Token`
- structured logs: request ID, service, latency, status, and safe exception type

Scale workers independently using queue age and processing latency. Never place the Supabase service-role key or AI provider key in the iOS application.
