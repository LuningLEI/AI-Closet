# Outfit library configuration

`config.json` is the single configuration entry point. Set `OUTFIT_CONFIG_PATH` to an absolute alternative JSON path for experiments. Prompt file paths resolve relative to that JSON file. API requests and each worker iteration reload the configuration; an in-flight task finishes with its existing snapshot. Restart processes only when changing the environment variable or Python provider implementation.

| Setting | Default | Effect |
|---|---|---|
| `generation_model` | `gpt-4.1-mini` | Generates combinations that contain the anchor |
| `evaluation_model` | `gpt-4.1-mini` | Independently assesses the complete proposed combination |
| `image_detail` | `low` | Input detail for both calls |
| `catalog_limit` | `40` | Maximum images in an anchor's generation request, including anchor |
| `candidates_per_anchor` | `8` | Maximum proposed combinations per task |
| `max_items_per_outfit` | `4` | Maximum members in a combination |
| `generation_prompt` / `evaluation_prompt` | `prompts/*.txt` | Editable prompt text |
| `request_timeout_seconds` | `120` | Each provider request deadline |
| `lease_seconds` | `1800` | Must exceed all possible request deadlines plus a safety margin |
| `max_attempts` | `3` | Maximum task attempts; failures can be explicitly retried |

Content hashes version prompts, model names, image detail and candidate policy. Changing inference settings enqueues a new pass for enrolled users. Old evaluations remain for audit; a changed evaluator is not silently mixed into the new version. Every saved evaluation contains its configuration snapshot, prompt text, scores, reasons, usage and item revisions. Provider switching is isolated in `provider.py`; model names can be changed directly for compatible OpenAI Responses models. A different vendor/API requires a provider adapter; arbitrary model names are not guaranteed compatible.

## Generation semantics

An anchor task chooses a bounded, role-balanced catalog with style-based prioritisation, then asks the model to propose up to eight combinations. Each combination must contain the anchor, only owned/available catalog IDs, no duplicates, and a complete core structure. Top+bottom or a full-body garment is required; optional outerwear/shoes/accessories and compatible two-top layering are supported. No current weather or target occasion is required. The generation prompt does consider internal thermal coherence, garment-purpose/formality compatibility, pattern balance, and deliberate solid-color contrast. Pattern, season, warmth, formality and occasion attributes are sent alongside the images. Changes to these item attributes now create a fresh anchor revision.

This is a bounded candidate library, not an exhaustive enumeration of every aesthetically valid combination. Completing a task with zero accepted outfits is valid and does not produce fake fallback outfits. The initial threshold is experimental and requires comparison with human annotations.

## State and safety

- A library is enrolled by a full `POST /api/v1/outfits/build` or the CLI without an anchor filter. Full-library builds and worker reconciliation automatically create anchor jobs only for clothing; Bags, Shoes, and Accessories remain available as candidates but do not each start a separate model run. A focused request with `anchor_item_id` is an explicit user action and can queue any ready item, including a bag, shoe, or accessory. It does not enroll a new user for a full wardrobe scan. Until first enrollment, uploads do not silently start model spending.
- Jobs use user+anchor+item revision+generation version keys. Repeated clicks and multiple workers do not create duplicate jobs. SQL claims use `FOR UPDATE SKIP LOCKED`, leases and completion fencing.
- A stored evaluation's ID is deterministic from user+sorted membership+member revisions+evaluator version. Finding A+B from B also reuses the result created from A. Concurrent evaluations may still spend tokens on the same combination, but cannot create duplicate records.
- A modified/deleted/not-ready member invalidates its stored variant in API reads. Legacy revisions remain readable when their previously tracked fields match, and are checked against current explicit compatibility rules. Worker reconciliation creates replacement tasks for changed anchors. A change during inference discards the stale result and retries within the attempt limit.
- Signed image URL rotations do not invalidate scores. Images must be replaced with new storage paths, as the existing upload flow does.
- `outfits` holds versioned evaluation rows; `outfit_items` holds membership. The API presents one base outfit per top/bottom or full-body member set. Outerwear, shoes and accessories are stored as complete optional-addition alternatives in `optional_additions`; alternatives are not merged into an unvalidated combination. Total and pagination count base outfits. Filtering by an optional item returns bases with a saved valid alternative containing that item. Old rows are retained for audit, not shown as duplicate outfits.
- This release does not change the production recommendation engine to draw from the new library. Weather, occasion and wear-history ranking are a later phase.

## Enable in Supabase

Run `backend/sql/migrations/007_outfit_library.sql` once in the project's SQL Editor. It creates four tables plus two service-role RPCs. Use the service-role key only on the backend. Owner-read RLS is enabled; clients cannot manufacture scores or claim jobs. The complete schema snapshot also includes the migration.

Start API, recognition worker (for new uploads), and outfit worker in separate terminals:

```bash
# From the project root
make backend-dev
make worker
make outfit-worker
```

In iOS open Closet → Outfits → Build outfit library. The API only queues jobs, it does not wait on image inference. Use the item selector or an item's “Outfits with this item” link to browse membership. Existing outfits remain browsable when a worker is stopped. During generation the UI shows pending/completed/failed counts and retries.

CLI (run from backend):

```bash
python -m workers.outfits --user-id YOUR_USER_ID --enqueue-only
python -m workers.outfits
# Process at most one queued anchor:
python -m workers.outfits --once
# Retry this user's failed tasks without making model calls in this command:
python -m workers.outfits --user-id YOUR_USER_ID --retry-failed --enqueue-only
```

Local development without Supabase uses `DATA_DIR/outfit_library.sqlite3` with transactional claims. Supabase projects never silently fall back to local storage if migration is missing; API responds with an actionable 503.

## Base-outfit policy (October 2026)

- Statement patterns on both a top and bottom are rejected when recorded pattern attributes identify them. Unknown pattern metadata is not guessed; generation also checks images.
- A puffer/down jacket with shorts or a short skirt is rejected. When reading an older saved variant, a valid base can remain without its incompatible outer layer.
- The model considers material, insulation, silhouette and formality together. These broader judgments still require visual review; they are not guaranteed by the two deterministic checks.
- Candidate selection reserves half the image budget for complementary core garments and ranks by compatibility. A white shirt/blouse gets priority for a black pencil skirt. The bounded catalog and model proposal limit are not exhaustive and do not guarantee every valid pairing.
- Monochrome, tonal, black/white and intentional solid-color contrast are allowed. Pink is not treated as inherently informal. Plain/plain remains valid.
- Explicit compatibility checks apply even when the aesthetic-score admission filter is disabled. Diagnostic scores on historical full variants are not fresh evaluations of their extracted base.
- Existing rows and membership tables retain the original generated combinations for audit; grouping is a read projection, so no destructive database migration is required.
- New generation prompt/attribute revisions cause a new anchor pass when the worker resumes. This is not a continuation with unchanged model inputs. The worker was stopped during deployment; do not run an old worker against this new config.

## Concurrent worker

`python -m workers.outfits --concurrency 3` runs three independent anchor consumers (default 3, allowed 1–8). Each thread owns its repository/client, claims only when ready, and processes one anchor at a time. A coordinator reconciles new/changed clothes for enrolled users while consumers run. Concurrency is a CLI option, not part of the generation version: changing it does not invalidate existing work. `--once` still processes at most one anchor and `--enqueue-only` does not call models.

PostgreSQL claims use SKIP LOCKED plus leases; SQLite claims use an immediate transaction. Deterministic result IDs and database uniqueness prevent duplicate stored combinations. Base-outfit grouping happens before API pagination. Two different anchors can still call the model for the same combination concurrently; this is result deduplication, not exactly-once inference or guaranteed cost deduplication. Begin with 3 rather than assuming high concurrency improves throughput under provider rate limits.

Ctrl+C/SIGTERM stops new claims and waits for active calls/tasks to finish. A hard kill still relies on lease expiry. Transient claim/reconciliation/config errors are logged and retried; repeated model errors remain bounded by the task retry policy. This adds concurrency only to outfit generation, not the separate recognition worker.

## Three-part compatibility filter

The active admission policy uses concrete compatibility issues and structured visual checks. Historical 1–5 scores remain exportable audit data but are not executable policy.

`OutfitConfig.compatibility_rules` supplies editable defaults; optionally add a `compatibility_rules` object to config.json **after restarting workers on this version**:

```json
{"block_double_statement_patterns": true, "block_thermal_conflicts": true,
 "block_purpose_conflicts": true, "very_warm_minimum": 5, "very_light_maximum": 1}
```

The three checks cover patterned top/bottom conflicts; puffers with short bottoms and recorded extreme upper/lower insulation mismatches; and dedicated athletic garments with office/formal garments or ski clothing with short bottoms. Formality uses subtype or corroborating formality and purpose/style attributes. Different occasion labels, a pink blouse, ordinary shirts with casual denim, and intentional solid-color contrasts are not rejection reasons. Missing attributes are not guessed. Visual shades, proportions and ambiguous garment purpose remain generation-model judgments, not guarantees of these deterministic rules.

These settings re-filter saved results on reads and validate new proposals. They do not change evaluator/generation keys or enqueue a new wardrobe pass. An incompatible optional addition is omitted while its valid base remains. Saved records are retained; previously discarded proposals cannot be recovered just by relaxing a rule. Restart API and outfit workers after Python changes. No database migration or recognition rerun is needed.

## Image-based generation → final image review (current default)

`pipeline_mode` defaults to `vision_then_visual`. Code first selects up to 40 catalog garments using recognized metadata. The first model then receives all selected garment images plus labels and proposes up to 8 outfits per anchor. The 40-item catalog selection itself still does not inspect images. Structural and explicit compatibility rules prefilter proposals. The second model receives each retained candidate's images plus metadata and returns `core` and `full` judgments. Each has `wearability`, `thermal`, `color_pattern` and `occasion` verdicts (`pass`, `fail`, `uncertain`) with reasons. All core checks must pass for new admission; full checks must also pass to admit optional additions. A score is not requested or used. Failed/uncertain reviews are saved for inspection, with the model, prompts, usage and item revisions. Transport/model failures retry through the existing job policy.

The only active mode is `vision_then_visual`. Editable prompts, models and limits live in `config.json`; restart workers and the API after changing them. Each generation run stores the resolved models, prompts, policy, taxonomy and Taste Profile versions in an immutable runtime snapshot.

This pipeline changes evaluator and job version keys. On restarting the worker, enrolled wardrobes receive a new version pass; completed old jobs/history are retained rather than deleted. Existing valid outfits remain visible with `visual_review_status: pending` (also separately on optional alternatives). These are historical previews, not new visual approvals. A current review supersedes the same historical full combination, and the latest current core review supersedes historical acceptance of that core. Failed/uncertain cores are hidden; failed optional alternatives cannot reappear through their old rows. Other old model versions never count as current approvals.

The new pass reviews its generated candidates, not necessarily every historical combination. Historical combinations not proposed again remain explicitly pending; exhaustive historical review requires a separate backfill. New jobs still propose a bounded number of candidates per anchor. No database schema migration is required: structured visual reviews are stored in the existing JSON payload. This is not an exactly-once model-call system.

## Vector catalog selection

The catalog stage reads only stored labels and vectors; it does not read images, call an LLM or generate embeddings. It excludes incompatible garment roles (tops/bottoms exclude full-body dresses, while tops retain skirts), explicit style conflicts, and existing thermal/pattern/purpose conflicts. Valid layered tops remain eligible. Metadata-ranked fallback handles absent, zero, invalid or dimension-mismatched semantic vectors.

Within complementary role groups, ranking uses cosine similarity of saved semantic vectors, plus metadata-vector similarity and existing preference bonuses. Missing semantic vectors use local metadata vectors instead. `catalog_rules` controls incompatible style pairs and ranking weights. Default style exclusions are Business/Sporty and Formal/Sporty; different styles or disjoint season tags alone do not imply incompatibility. Thermal checks concern internal garment compatibility, not today's forecast. Unknown attributes do not create hard exclusions.

The anchor is included in the 40-item cap. Half the remaining budget is reserved for complementary core roles; unused slots are filled round-robin across compatible roles. Fewer than 40 is valid; excluded items are never added just to fill the cap. Generation and final visual review still receive images. Catalog-policy changes version new generation tasks while preserving the visual evaluator key. V1 experiment code is unchanged; V2 has its own copy of this selector. Previously frozen V2 runs remain reproducible with their archived source; create a new run to use this updated selection policy.
