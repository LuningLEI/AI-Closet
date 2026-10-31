# Database Migrations

Use these files to understand schema evolution. `backend/sql/schema.sql` remains the full idempotent snapshot that can be pasted into Supabase SQL Editor for a fresh environment.

Recommended workflow:

1. Add a new numbered migration for each schema change.
2. Keep migrations idempotent where practical.
3. Update `backend/sql/schema.sql` so new environments can still be created from one file.
4. Record application-level changes in `docs/architecture/system.md` when the data model changes.
5. Do not introduce app-only database fields without adding corresponding Pydantic models and OpenAPI updates.

Current migration history:

- `001_core_closet_schema.sql`: core closet tables, recognition records, feature snapshots, and pgvector.
- `002_user_isolation_rls.sql`: user ownership, RLS policies, and private storage policies.
- `003_recognition_queue.sql`: durable recognition jobs, retries, leases, and dead-letter support.
- `004_profile_preferences.sql`: structured profile/preference columns and preference feature data.
- `005_structured_recognition_fields.sql`: typed recognition attributes for upload analysis and model-ready datasets.
- `006_item_edit_events.sql`: append-only, user-scoped corrections to clothing-card fields and image transforms.

- `007_outfit_library.sql`: per-user outfit membership, versioned evaluations, enrollment and leased anchor generation queue; backend-only model writes and owner-read RLS.
- `008_atomic_items_and_current_outfits.sql`: atomic item commits, transactional refresh requests, current core/layer projections and database-side pagination. Apply after 007.
- `009_outfit_runs_and_retention.sql`: immutable run manifests, individual model-call accounting, queryable review status, current evaluation provenance and preview-first retention. Apply after 008. Existing audit history is preserved; legacy billing is not reconstructed.

Upgrade with API/workers stopped: apply 008 (if missing), then 009; rebuild the read model with
`python -m tools.admin.refresh_outfit_projection --all-users`, then restart API/workers.
The rebuild reads saved evaluations only and makes no model requests.
Do not run the complete schema file over a production database as an upgrade procedure.

- `010_outfit_error_diagnostics.sql`: additive safe JSON diagnostics on model calls. Apply after 009, before running the updated outfit worker. No queue resets or retries.
- `011_outfit_call_job_delete.sql`: fixes clothing deletion blocked by `outfit_model_calls_job_id_fkey`. Deleted jobs detach their call ledger via `ON DELETE SET NULL`; run, token and cost records remain. New calls still require a live job lease. The migration itself deletes no items and retries no jobs.

- `012_personal_outfits_and_wear.sql`: independent user-created compositions and idempotent wear history; owner-read RLS and ownership-checked service-role RPCs. Extends the paginated library query to include personal outfits even with the generation worker stopped. Apply after 011, then restart the API and rebuild the iOS app. No model jobs are enqueued by this migration. It preserves clothing, labels, generated evaluations and cost history.
- `013_personalized_outfit_feedback.sql`: append-only Like/Not-for-me events, exact-composition feedback state and a separate per-user taste-profile projection. Apply after 012. Feedback writes do not update `user_preferences`, rebuild outfits or call a model.
- `014_liked_outfits.sql`: renames the former Adopt feedback state to Like and preserves existing feedback history.
- `015_daily_outfit_selection.sql`: persists one replaceable Today selection per user-local date, keeps wear history, and supports durable cancel/restore behavior across screens and app launches.
- `016_preserve_outfits_on_profile_edits.sql`: stops profile and personal taxonomy edits from deleting the published outfit library; recommendation ranking reads these preferences live.
- `017_taste_profile_learning.sql`: captures immutable outfit feature snapshots, backfills existing feedback/wear/personal Outfit sources, and enables deterministic per-user taste projection/reset. Apply after 016 before starting `taste_profile_worker`.
- `018_free_text_taste_summary.sql`: adds low-frequency per-user feedback-note summaries, compare-and-set publication, and a model-usage ledger. Apply after 017 before starting `free_text_taste_worker`; the worker waits for 10 pending notes and never triggers outfit regeneration.
- `019_taste_profile_v2_defaults.sql`: promotes the simulation-selected Taste defaults, changes the profile algorithm version to `taste-profile-v2`, and marks existing projections for deterministic replay. Apply after 018 before restarting `taste_profile_worker`; it preserves feedback, outfits, wear history and explicit preferences and makes no model calls.
