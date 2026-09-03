# Database Migrations

Use these files to understand schema evolution. `backend/sql/schema.sql` remains the full idempotent snapshot that can be pasted into Supabase SQL Editor for a fresh environment.

Recommended workflow:

1. Add a new numbered migration for each schema change.
2. Keep migrations idempotent where practical.
3. Update `backend/sql/schema.sql` so new environments can still be created from one file.
4. Record application-level changes in `docs/ARCHITECTURE.md` when the data model changes.
5. Do not introduce app-only database fields without adding corresponding Pydantic models and OpenAPI updates.

Current migration history:

- `001_core_closet_schema.sql`: core closet tables, recognition records, feature snapshots, and pgvector.
- `002_user_isolation_rls.sql`: user ownership, RLS policies, and private storage policies.
- `003_recognition_queue.sql`: durable recognition jobs, retries, leases, and dead-letter support.
- `004_profile_preferences.sql`: structured profile/preference columns and preference feature data.
- `005_structured_recognition_fields.sql`: typed recognition attributes for upload analysis and model-ready datasets.
