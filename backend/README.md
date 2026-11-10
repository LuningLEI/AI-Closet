# Backend

For architecture, tradeoffs and interview preparation, read the [system guide](../docs/architecture/system.md) and [database guide](../docs/architecture/database.md).

FastAPI service for AI Closet.

## Responsibilities

- Authenticated API routes
- Supabase repository access
- Private Storage upload and signed URL generation
- OpenAI Vision recognition
- Embedding generation
- Recognition queue worker
- Weather-aware and preference-aware recommendations

## Run

```bash
cd backend
/opt/anaconda3/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Worker:

```bash
cd backend
/opt/anaconda3/bin/python -m workers.recognition
```

## Check

```bash
cd backend
/opt/anaconda3/bin/python -m compileall app
```

Run tests:

```bash
cd backend
/opt/anaconda3/bin/python -m pytest
```

## AI provider configuration

Production model calls use one application-owned gateway contract. Responses-style
providers use `AI_PROVIDER=openai-compatible`; hosted open-weight VLMs exposing
OpenAI-compatible Chat Completions use `AI_PROVIDER=chat-completions`. Before a
deployed provider switch, set `AI_ALLOWED_MODELS` to a comma-separated allowlist
and set `AI_CHAT_SCHEMA_MODE` to the strongest mode verified for that exact
provider/model pair. Provider comparisons must use the read-only shadow tools
under `tools/evaluation/`; they never replace production recognition or outfits.

## Direct-Vision Baseline Evaluation

This is separate from the production recommender: OpenAI receives closet images labelled only with image codes, returns strict JSON using those codes, and the evaluator maps them back to the private catalog.

```bash
cd backend
/opt/anaconda3/bin/python -m tools.evaluation.baseline_eval \
  --user-id YOUR_SUPABASE_USER_ID \
  --temperature-f 75 \
  --occasion Vacation \
  --style Casual \
  --looks 5 \
  --max-images 40 \
  --open
```

It writes `report.html`, `results.csv`, `result.json`, and `raw_response.json` under `evaluation/baseline_runs/` (at the project root). Use `--max-images 0` only when deliberately sending every eligible closet photo; it can be slow and costly.

## Recommendation Method Comparison

This experiment creates a single human-readable comparison across three methods: a contact-sheet vision stylist, database semantic-vector ranking, and the current hybrid recommender. The vision method receives only I-code-labelled contact sheets; it does not receive catalog metadata, vectors, or ranking rules.

```bash
cd backend
/opt/anaconda3/bin/python -m tools.evaluation.comparison_eval \
  --user-id YOUR_SUPABASE_USER_ID \
  --temperature-f 45 \
  --temperature-f 60 \
  --temperature-f 72 \
  --temperature-f 85 \
  --occasion Everyday \
  --style Casual \
  --looks 3
```

Repeat `--temperature-f` and `--occasion` to evaluate every temperature/occasion combination. Each contact-sheet vision scenario is a separate OpenAI request and can take minutes, so start with one occasion and a small scenario set.

The output folder contains an `index.html` with links to every scenario, per-scenario `comparison.html`, `comparison.csv`, and `prompts.json`, plus one `comparison_all_scenarios.csv` covering the entire run. Add `--archive-source-images` only to create a local `I-code` ZIP for inspection; the ZIP is never sent to the model.

Each scenario report saves its selected garment images locally, so it remains viewable after the original Supabase signed URLs expire. To repair an older report that still contains expired URLs, without making an OpenAI request:

```bash
/opt/anaconda3/bin/python -m tools.evaluation.comparison_eval \
  --user-id YOUR_SUPABASE_USER_ID \
  --refresh-images-run ../evaluation/outfits/comparison_runs/20260921-133521
```

The vector method uses each item's stored `semantic_vector`: an embedding of its structured recognition text (category, subtype, color, seasons, styles, occasions, and summary). Its query is an embedding of the requested context plus saved preferences. It ranks structurally valid candidate outfits by cosine similarity only; it is intentionally not a raw-image-vector search and does not apply the hybrid engine's weather, occasion, color, compatibility, or diversity scores. The current hybrid model also makes one context-embedding request per recommendation, then performs its candidate generation and scoring locally; the comparison report records both methods' embedding input tokens.

## Human Evaluation Workbook

Create a two-sheet Excel workbook for blinded clothing labels and outfit judgments. It embeds private garment thumbnails locally and makes no OpenAI calls.

```bash
cd backend
/opt/anaconda3/bin/python -m tools.evaluation.human_eval_workbook \
  --user-id YOUR_SUPABASE_USER_ID \
  --outfit-count 100
```

The `Garment Labels` sheet contains one garment per row and blank occasion, style, and season labels for three human annotators plus `baseline-picture` and `baseline-vector`. The `Outfit Judgments` sheet contains 100 randomized structurally valid outfits, each with a varied prompt and two five-rater columns: wearability and aesthetics. Both use the three-way verdict dropdown: `Inappropriate`, `Neutral`, or `Appropriate`.

### Recognition model shadow evaluation

Use the shadow harness before changing the production recognition provider. It
freezes stored production labels and item-card-confirmed labels, calls the
candidate endpoint, and writes only below `evaluation/model_migration/recognition_shadow/`.
It never updates garments, recognition history, jobs, embeddings, or outfits.

First prepare a small category-balanced smoke test; this makes no model calls:

```bash
python -m tools.evaluation.recognition_shadow prepare \
  --user-id YOUR_SUPABASE_USER_ID \
  --model CANDIDATE_MODEL_ID \
  --model-revision CANDIDATE_REVISION \
  --base-url https://candidate.example/v1 \
  --protocol chat-completions \
  --limit 10 \
  --baseline PATH_OR_ID_OF_RECOVERY_BASELINE
```

For a memory-constrained local vision endpoint, add
`--image-max-dimension 448 --output-max-tokens 512`. The harness downloads each signed source image,
applies EXIF orientation, resizes it proportionally in memory, and sends a
JPEG data URL without persisting the source URL or resized image. Leave the
image option at its default `0` when evaluating a remote provider on original
input. The output cap is also versioned in the run manifest.

Set `SHADOW_AI_API_KEY` outside source control, then run the returned directory:

```bash
python -m tools.evaluation.recognition_shadow run --run-dir SHADOW_RUN_DIRECTORY
```

For a paired remote comparison, clone one prepared run and give every provider
the same positive `--image-max-dimension` (for example `2048`). Each result
records the exact JPEG dimensions and SHA-256 so matching item hashes can be
verified across runs. Native Gemini structured output is supported with
`--protocol gemini-generate-content`,
`--base-url https://generativelanguage.googleapis.com/v1beta`, and
`--api-key-env GEMINI_API_KEY`. Hugging Face router runs use
`--api-key-env HF_TOKEN`. Provider keys belong in the local environment or
untracked `.env`, never in a run manifest.

Each garment is committed as an independent JSON result, so the same command
resumes safely after interruption. `--max-items 1` is useful for the first real
request; `--retry-failures` is explicit because retries may cost money. Use
`--allow-no-api-key` only for a trusted local endpoint. Once the smoke test is
valid, prepare a new run with `--limit 0` for all eligible garments.

Per-item results retain the redacted raw provider payload and text, cleaned
text, parsed prediction, scalar-normalization input, and final normalized
prediction. Known trailing Kimi control tokens are removed only from the
cleaned copy. Signed URLs and in-memory image data are redacted from audit
output.

`summary.json` reports schema/model-call success, latency, usage and optional
configured cost; agreement with current production labels is kept separate from
accuracy on item-card-confirmed human labels. `results.csv` contains item-level
disagreements for review. Rebuild metrics without calls using:

```bash
python -m tools.evaluation.recognition_shadow summarize --run-dir SHADOW_RUN_DIRECTORY
```

### Occasion recognition scores

Vision recognition returns independent 0–1 suitability scores for every occasion (not calibrated probabilities and not a distribution that sums to one). **All scores, including those below the threshold, are saved** in `clothing_items.recognition_tags.occasion_scores` and the historical `recognition_records.normalized_payload.occasion_scores`. The stored `occasion` and `occasion_threshold` are recognition-time snapshots, not the source of truth for current automatic display or occasion scoring.

Set `RECOGNITION_OCCASION_THRESHOLD=0.8` (0–1) and restart the API to change display labels and recommendation occasion scoring for already-scored items. Both derive their labels from the complete saved scores using the current **>=** threshold, without another vision call or rewriting scores. Restart workers too to keep newly saved snapshots consistent. API responses include `recognition_tags.display_occasion_threshold` separately from the original threshold. If no score reaches the threshold, automatic selection falls back to the single highest-scoring occasion. Ties use taxonomy order. The same rule applies to new recognition snapshots, API display, and recommendation matching; complete scores are retained. Explicit manual removals still take precedence, including an intentionally empty manual selection. Historical recognition snapshots keep the rule output from when they were created.

iOS item details show only the editable Occasion multi-select; model scores and the threshold are not shown to end users. Inspect complete scores through the database or the CLI evaluation report. New edits store per-occasion additions/removals: display and recommendation use `(model labels above the current threshold ∪ manual additions) − manual removals`. Editing other fields does not freeze automatic occasion selection; original scores remain available. Older manually edited items without override metadata retain their saved selections. Legacy results and filename fallbacks have no occasion scores and retain their existing labels; re-recognize the image to obtain scores. Recommendation embeddings and historical snapshots are not regenerated by a threshold-only change. Scores use existing JSON payload columns, so no database migration is required.

To inspect raw occasion suitability scores on a reproducible sample of local photos, run from `backend/`:

```bash
python -m tools.evaluation.evaluate_occasion_scores --images ../closet_picture --count 10 --seed 42
```

This sends the sampled photos to the configured OpenAI vision model using the production prompt and image detail setting. It writes an image report, all scores as CSV, and normalized results as JSON under the project-root `evaluation/occasion_samples/`. The report applies no threshold and does not update closet records. Each photo is sent once; API errors stop the run without substituting heuristic results.

## Reset a user's recognition results (CLI)

Reuse existing stored images after changing the recognition model, prompt, detail level, or occasion threshold. No upload or schema migration is needed. Run this as an offline maintenance command: **stop all recognition workers and other writers before applying it**, then restart workers afterward so they load the new configuration. Local JSON storage does not support concurrent writers; Supabase resets also span multiple requests rather than a database transaction.

From `backend/`:

```bash
# Preview the affected item IDs without changes.
python -m tools.admin.reset_recognition --user-id YOUR_SUPABASE_USER_ID --dry-run

# Mode 1 (default): keep manually corrected items unchanged.
python -m tools.admin.reset_recognition --user-id YOUR_SUPABASE_USER_ID --keep-manual

# Mode 2: reset every item, including manually corrected items.
python -m tools.admin.reset_recognition --user-id YOUR_SUPABASE_USER_ID --include-manual

# Or test only 10 items, oldest first.
python -m tools.admin.reset_recognition --user-id YOUR_SUPABASE_USER_ID --limit 10

# Restart the worker with the desired model/detail/threshold settings.
python -m workers.recognition
```

- The user UUID is mandatory; other users are untouched. Supabase mode requires the existing service-role credentials for administrative writes. The command uses the same repository configuration as the backend.
- Two mutually exclusive modes: `--keep-manual` (default) skips entire manually corrected items; `--include-manual` resets them too. Both support `--dry-run` and `--limit`. The output records the chosen mode. Historical edit events are retained in either mode; clearing corrections means replacing current attributes, not deleting history.
- Resets current clothing attributes, recognition scores/tags, confidence, and recommendation vectors. Keeps item IDs, image paths, image URLs, and creation dates. The worker refreshes signed URLs from storage paths and rebuilds recognition results and embeddings. HTTPS-only legacy references remain usable only while their URLs are valid; local-only images still follow the worker's existing heuristic fallback behavior.
- Replaces previous queue jobs for selected items with fresh queued jobs (attempts reset to zero). A repeat reset does not accumulate duplicate jobs. Historical recognition records, feature snapshots, and edit events are retained for comparison.
- Saves complete pre-reset item and queue snapshots to `data/recognition_resets/<run-id>/before.json`; `result.json` records progress. Processing jobs block the reset. Let running jobs finish before stopping the workers; interrupted leases must be resolved through the existing worker timeout/retry lifecycle first.
- On a write error, the command stops, attempts to restore the failed item's previous state and jobs, and exits nonzero. Already-completed resets remain queued. Inspect the printed progress report and backup before restarting workers if rollback failed. This is not an atomic whole-user operation.
- The reset command makes no model calls. The restarted worker uses its own environment, including `OPENAI_VISION_MODEL`, `OPENAI_VISION_DETAIL`, and `RECOGNITION_OCCASION_THRESHOLD` (default `0.8`). An already-running worker will not pick up changed `.env` values.

### Monitor the current reset batch

Keep the worker running in terminal A. In terminal B, watch the latest reset for the user:

```bash
python -m tools.admin.recognition_progress --user-id YOUR_SUPABASE_USER_ID --watch
```

The command refreshes every 5 seconds and exits with an explicit completion message only when every item in that batch has a completed job. Omit `--watch` for one snapshot, or add `--run-id RESET_BATCH_UUID` to select an older batch. `Ctrl+C` stops monitoring only. Waiting retries are counted as unfinished; permanent failures, missing/replaced jobs, and incomplete resets prevent an all-complete result. Exit code 2 means the batch needs attention; lookup errors return 1. Job completion includes the pipeline's heuristic fallback, so this measures processing completion rather than vision accuracy.

Run on the machine containing `data/recognition_resets/` for this reset. New batches save exact job IDs and atomic progress reports. Existing batches are supported by matching item IDs and job creation times within the original reset window. Monitoring is read-only and does not pause workers or call a model.

### Occasion manual-edit audit fields

`item_edit_events.changes.occasion` keeps `before` and `after` strings and adds `added`, `removed`, `threshold_at_edit`, `model_selected_at_edit`, and `effective_after`. Before/after describe the user's editing snapshot; effective_after records the saved merged selection under the current server threshold. Model candidates are null for legacy items without scores. Arrays use taxonomy order, and selection ordering alone does not count as an edit.

Current overrides live in `clothing_items.metadata.occasion_overrides` as `{ "added": [...], "removed": [...] }`. Re-adding a removed label clears its removal and records an explicit addition; removing an added label does the reverse. Model scores are never changed by an edit. Threshold-only changes create no manual-edit event. Both fields are existing JSONB columns; no SQL migration or historical event rewrite is needed.

iOS send optional `occasion_before` and `occasion_threshold_at_edit` with saves. The backend validates the snapshot against the existing item at that threshold; conflicting selections return HTTP 409 before writes. Clients without snapshots use the server's current effective selection as the baseline. `--keep-manual` preserves edited items and overrides; `--include-manual` clears active overrides as part of resetting the item, while retaining audit history.

### Per-user, per-occasion thresholds

Each user's `user_preferences.preferences.occasion_thresholds` JSON object can override the threshold for each occasion. Missing entries use `RECOGNITION_OCCASION_THRESHOLD` (default `0.8`). For example, `{ "Everyday": 0.85, "Work": 0.7 }` makes Everyday harder and Work easier to match for this user only. All matching labels are selected; if none match, the highest raw score wins (taxonomy order breaks ties). Manual additions/removals continue to take precedence.

From `backend/`:

```bash
# Show this user's resolved thresholds.
python -m tools.evaluation.occasion_thresholds --user-id USER_UUID

# Change selected thresholds. Other occasions and users retain their settings.
python -m tools.evaluation.occasion_thresholds --user-id USER_UUID --set Everyday=0.85 --set Work=0.7

# Reset every threshold for this user to 0.8, and refresh stored labels.
python -m tools.evaluation.occasion_thresholds --user-id USER_UUID --reset-defaults --reapply

# Preview/reapply current policy to all stored scores, without another model call.
python -m tools.evaluation.occasion_thresholds --user-id USER_UUID --reapply --dry-run
python -m tools.evaluation.occasion_thresholds --user-id USER_UUID --reapply
```

The API reads preferences on each request, and the worker reads them per job, so policy edits require no process restart once this code is deployed. iOS edit snapshots include the complete map (`occasion_thresholds_at_edit`); audit records store `thresholds_at_edit`, with the legacy scalar `threshold_at_edit` set to null when thresholds differ. New recognition snapshots store `occasion_thresholds`; full raw scores are unchanged.

`--reapply` updates only `clothing_items.occasion`, backs up affected items under `data/occasion_reapplications/`, skips pending/unscored items, and preserves manual overrides and historical recognition records. It rechecks items before updating and reports changed/deleted records as conflicts; run while other writers are idle because this is not an atomic bulk transaction. No SQL migration is required. The future learning algorithm can read the manual edit events and call `update_user_thresholds`; automatic learning is not enabled yet.

## Retained evaluation results

Evaluation artifacts now live in [`../evaluation/`](../evaluation/README.md), outside the backend:
- `recognition/single_occasion/`: original single-label workbook and evaluation.
- `recognition/multi_occasion/`: current recognition scores with the any-match occasion hit rule.
- `outfits/comparison_runs/20260921-133521/`: retained comparison run, including local report images.

Evaluation commands still run from `backend/` because they use application services. New workbook drafts default to `evaluation/drafts/` at the project root. All other evaluation generators also default to the project-root evaluation directory. Recompute the retained multi-occasion analysis with:

```bash
python -m tools.evaluation.analyze_human_eval --workbook ../evaluation/recognition/multi_occasion/annotation.xlsx --output-dir ../evaluation/recognition/multi_occasion/analysis
```

## Personal outfit library

Closet now supports **Items / Outfits**, an item membership filter and outfit details. Outfit quality is evaluated independently of weather and occasion. Models, prompts, thresholds and generation limits live in [`app/outfits/config.json`](app/outfits/config.json); see the [outfit library guide](app/outfits/README.md) for version semantics and commands.

Apply `sql/migrations/007_outfit_library.sql` in Supabase before using the new endpoints, then run `python -m workers.outfits` alongside the API and recognition worker. Tap **Build outfit library** once to enroll the user; future ready items are queued automatically by that worker. No model calls run inside a frontend request. This initial library does not replace the existing recommendation engine yet.

### User-confirmed item labels

Opening an iOS detail card sends its displayed label snapshot via PATCH with
`edit_source=ios_card_open`. Confirmation is persisted in
`metadata.label_confirmation`; it is not logged as a manual label correction and
makes no embedding call. Changed snapshots clear the old semantic vector for the
existing background repair loop. Confirmed occasion labels do not drift when
thresholds change. Actual label saves replace the confirmation snapshot.

Photo rotation/cropping saves preserve labels and vectors, without enqueueing
recognition. Recognition writes compare the current metadata, image and label
snapshot atomically; intervening confirmation/edits prevent stale writeback.
Machine recognition records remain separate from the confirmed card. Reload API,
recognition workers and rebuild iOS to activate this behavior. No SQL migration.

### Wearing capabilities (recognition prompt v3)

Recognition returns `wearing_profile` with nullable booleans `can_wear_alone`,
`can_layer_over`, `can_layer_under`, `requires_inner_layer`; nullable
`closure_type` (pullover/buttons/zipper/open_front/wrap/other); `wearing_modes`
(standalone/inner_layer/outer_layer_closed/outer_layer_open); and image-grounded
`evidence`. Null means unknown/not applicable, not false. These describe garment
capabilities, not a selected mode for a particular outfit, and do not change taxonomy.

Stored at `clothing_items.recognition_tags.wearing_profile` and
`recognition_records.normalized_payload.wearing_profile`; effective feature
snapshots include the profile too. Existing JSON columns suffice: no SQL migration.
Legacy items default to unknown. Heuristic recognition does not fabricate capabilities.
Manual label changes preserve the profile. Image transforms preserve it with the labels.
The production outfit provider includes it in generation and review metadata; image
review remains necessary. This change does not add a frontend editor or per-outfit
structured wearing-mode selections, and does not automatically re-recognize old items.

### Consolidated catalog and color tones (recognition prompt v4)

Travel includes Vacation (historical scores merge by max; an explicit Travel threshold
wins over a legacy Vacation threshold). Crop Top is no longer a subtype: `length=Cropped`
is independent of garment construction. Dresses use Slip/Shirt/Wrap/Sweater/T-shirt/A-line
Dress; old Mini/Midi/Maxi values translate to Thigh/Midi/Maxi length without inventing a
construction subtype. Playsuit aliases Romper, Matching/Co-ord aliases Two-piece Set,
Pumps aliases Heels. Suit Set remains distinct. Cardigan belongs to Outerwear. Inner-layer requirements are determined by
wearing_profile, never forced by subtype. Unknown does not satisfy an explicit
requires_inner_layer constraint. Frontend create/edit catalogs match these options.

`color_tones` is a list in recognition_tags / normalized_payload, with one record per
identified color: canonical color tag, nullable hue (HSL degrees 0–360), saturation
(0–1), lightness (0–1), and evidence. These are uncertain image-based estimates, not
calibrated fabric measurements. Low lightness is dark; high lightness is light; high
saturation is vivid. Unknown is null. The user still edits broad color tags; removing a
color removes its associated tone from effective metadata. The outfit provider includes
these coefficients, and revisions include them to avoid reusing mismatched evaluations.
No hard-coded color-label-to-tone conversion, new database columns, or automatic paid
re-recognition is required. Existing evaluation workbooks and V1/V2 experiment archives
are unchanged.

### Directional layering policy (recognition prompt v5)

`can_wear_alone=false` does not imply `requires_inner_layer=true`. A non-standalone
sheer top can have an opaque tank inside OR a T-shirt outside. A required-inner
flag instead fixes the direction. Each explicit relationship needs an inner piece
with can_layer_under=true and an outer piece with can_layer_over=true. A consistent
inner-to-outer ordering is required (cyclic mutual requirements are invalid).
can_layer_over=true alone does not force a companion when standalone is allowed.
Unknown legacy profiles may be offered for visual review but cannot satisfy an
explicit mandatory relationship. The final image review checks actual coverage,
opacity and fit: two sheer pieces do not automatically provide sufficient coverage.

A covering Outerwear piece required by a core top is retained in the core rather
than removed as an optional layer. Cardigan remains a taxonomy alias for Outerwear,
but no longer has a special capability assignment or filtering rule. Old stored
machine judgments are not automatically rewritten or re-recognized by this change.

### Lower-body layering (recognition prompt v6)

`wearing_profile` adds nullable `layering_region` (upper_body/lower_body/full_body)
and `lower_layer_role` (base/outer). Capabilities now refer to the garment's body
region. Only an explicit lower base with can_layer_under=true and a lower outer
with can_layer_over=true may occupy two bottom slots. Unknown profiles do not
permit a two-bottom combination. Rules support leggings under suitable shorts,
skirts, or an explicitly compatible dress, without allowing two ordinary trousers.
Upper layers cannot satisfy lower-body coverage requirements. Necessary lower layers remain core; removable lower layers are optional. The final image review checks fit, coverage and warmth;
capability tags alone do not guarantee an aesthetically or physically valid outfit.
A layered lower base is not automatically rejected as an athletic/formal conflict.

This extends the production outfit-library candidate selection, generation and
review pipeline. It does not change the archived V1/V2 experiments or the separate
legacy recommendation generator's single-bottom Candidate schema. Existing items
without new recognition data remain unknown; no paid re-recognition is launched.

### Tights / pantyhose (recognition prompt v7)

Tights stay under Intimates and occupy a hosiery/accessory slot, with lower-body
layering capabilities. Only skirts, shorts or dresses provide their outer cover.
Trousers, jeans, wide-leg pants, leggings and jumpsuits are incompatible even when
a skirt is also present. The restriction applies to candidate retrieval, complete
outfit validation and legacy recommendation validation. Historical unknown hosiery
capabilities remain eligible under this narrow rule, but explicit false capability
flags block the relationship. When hosiery is needed by an otherwise non-wearable
core, it is retained as core; it is optional only if the rest is independently valid.
Visual review still checks actual coverage rather than assuming all tights are opaque.


### Higher bar for optional layering

The outfit library selects a stable minimal structurally wearable base. Required
coverage stays in that base. Extra upper layers, lower layers and tights need an
explicit `optional_layering.verdict = clear_improvement` from the image reviewer,
in addition to passing the full outfit checks. The reviewer compares full versus
base for a substantial visual improvement in silhouette, proportion, texture or
color. Merely compatible, warmer, redundant or uncertain layers are not offered.
This is a categorical visual requirement, not a numeric aesthetic cutoff on basic
outfits. Rejected optional layers leave the passing base available. Historical
reviews missing this assessment do not authorize optional layers; raw evaluations
are preserved. Prompt hashes invalidate review caches for subsequent builds.
Restart the API and outfit worker to load the change; existing results are not
automatically sent for paid model review.

### Outfit run accounting and retention (migration 009)

Apply 008 and then 009 before running this backend revision. See
See the [database guide](../docs/architecture/database.md) and
[migration instructions](sql/migrations/README.md) for rollout and maintenance commands.
New generation batches freeze the model/prompt/config once. Each model request has its own
usage entry, including failures/unknown outcomes; cached evaluation reuse is linked without
inventing a paid call. `outfit_run_summary` reports progress and costs. Configure optional
`pricing` entries by model in the outfit config with `input_per_million`,
`cached_input_per_million`, `output_per_million`, `source`, and `as_of` (USD rates).
No default prices are assumed. An incomplete cost is null, with known subtotal and unknown-call
count reported separately. Legacy configurations remain readable for exports.

Retention is preview-first. Only terminal unpinned calls' raw usage JSON becomes eligible after
180 days; typed usage/cost counters, audit results and human correction events remain.

### Resumable batch uploads

`POST /api/v1/items/upload-batch` accepts optional multipart `upload_ids`: a JSON
array containing one unique stable string per file (maximum 128 characters each).
Clients must retain those IDs when retrying. The backend derives an item UUID from
the authenticated owner, upload ID, and SHA-256 of the bytes. Identical retries reuse
the item and image path; different selections or different bytes remain independent.
The existing item primary key and atomic `create_item_with_records` RPC arbitrate
concurrent commits. No new SQL migration is needed for this change; migration 008
must already be installed. Older clients without IDs retain their prior behavior.

Per-file failures, including a batch with zero successes, return HTTP 200 with
`items` and `errors`. Invalid batch metadata and authentication still produce HTTP
errors. A lost response can be retried safely with the same IDs and bytes. This is
whole-file retry, not byte-range resumable transfer or content-based deduplication
across separate user selections.

iOS persists prepared image bytes and their IDs in an account-scoped Application
Support queue before sending. Confirmed files are removed after each response;
unknown/failed files survive app restarts and can be retried with **Retry pending
uploads**. Queue files use iOS file protection and are excluded from backup. Uploads
do not continue while the app is terminated, and reinstalling the app removes its
queue. Keep the pending queue rather than reselecting the same photos to avoid
creating a new logical upload.

Storage transport retries reuse the same object path. Do not immediately delete
an object after a database exception: the transaction may have committed before
its response was lost. Retrying reconciles this situation, but permanently abandoned
uploads can still leave unreferenced objects; automated orphan cleanup is not yet
implemented. Recognition workers now survive claim/processing database exceptions;
persisted leases remain available for normal timeout recovery. Terminal failed jobs
still require explicit intervention after their configured attempt limit.

### Required footwear and optional accessories

The current outfit configuration sets `require_shoes: true`: a complete base is
upper/lower clothing (including necessary coverage layers) or a one-piece outfit,
plus exactly one supplied pair of shoes. Footwear is retained in the core and its
ID participates in base deduplication. A different shoe produces a different
complete base; changing optional hats/scarves/sunglasses does not.

Candidate retrieval reserves a footwear candidate before filling optional slots.
When no compatible recognized shoes are available, an anchor completes without
calling the generation model. The model cannot invent missing footwear. Local
validation rejects shoeless proposals even when the provider returns them.

Different accessory types can coexist (for example hat + scarf + sunglasses),
but duplicate types and multiple bags are rejected. ALL removable additions,
including accessories, must pass the existing `optional_layering` review with
`clear_improvement`, plus full-outfit compatibility. Every extra piece must visibly
contribute; merely matching or being useful is insufficient. This is a categorical
visual comparison against the complete base, not a new numerical aesthetic cutoff.
The full-outfit cap is now six items so a three-piece base can accommodate up to
three optional pieces; necessary layers also count toward the cap.

Prompt and policy keys invalidate generation/review caches and the current display
projection. Existing historical evaluations remain stored; under the current
policy, shoeless combinations are not displayed as complete outfits. Archived
experiment source files are unchanged. Run snapshots without `require_shoes`
retain the previous false default. Apply existing database migrations, restart the
API and outfit worker, and rebuild the projection if an immediate display refresh
is needed. No new SQL migration is required. Running the worker under this policy
can enqueue new generation jobs and incur model charges.

### Clothing-first footwear pipeline

Current configuration enables `footwear_pipeline`. The older joint generation path
and archived experiments remain available; run snapshots without the new setting
use the older path. The new sequence is:

1. Generate at most eight clothing combinations from clothing images and labels,
   without shoe images or shoe IDs. Reserve one item slot for mandatory footwear.
2. For each distinct valid clothing combination, rank footwear against ALL core
   garments and shortlist up to eight shoes with diversity across shoe subtypes.
3. A separate image-based selector compares those candidates, describing material,
   thermal use, shaft height, visual weight, purpose, and evidence. It may return
   no suitable shoe. These descriptors are per-evaluation evidence, not calibrated
   measurements or silently overwritten recognition labels.
4. An independent image call reviews the selected shoe against the clothing and
   alternatives. It receives no selection reasoning. Thermal coherence, formality,
   proportions, material balance, and comparison must all pass. Any uncertainty,
   failure, or clearly better supplied candidate blocks admission.
5. Run the existing complete-outfit visual review, retaining its higher bar for
   optional accessories/layers. A bad optional addition does not invalidate a good
   clothing-and-shoes base.

There is no blanket ban on skirts with snow boots: a winter knit/wool ensemble can
work, while delicate summer skirts and formal office outfits require different
footwear. Suitability is evaluated from images, not the broad Boots label alone.
A shoe anchor is compared with alternatives, never forced into an outfit. Only
results actually containing it are saved for its job.

`footwear_catalog_limit`, selection/review models, and the three new prompt files
are replaceable configuration. Call accounting uses existing `generation` stages
for clothing generation/footwear selection and `evaluation` for independent shoe
review/full review. Payload `footwear` links the exact selection/review call IDs,
profiles, candidate IDs, and shoe-pool revision. Rejected selections/reviews are
preserved in bounded per-job `stats.footwear_rejections`. No new SQL migration is
required (008/009 must already be installed).

Adding/editing/deleting a ready shoe changes the comparison pool and creates new
job identities; previous comparisons are not silently reused against different
alternatives. This can enqueue a new pass over existing garments. Historical rows
remain stored, but the new projection admits only results with matching footwear
review evidence and the current shoe pool. Projection refresh is eventually
consistent. The candidate shortlist is not an exhaustive wardrobe comparison.

Worst-case model calls are one clothing-generation call plus three calls per
unique proposal (selection, shoe review, full review): 25 for eight proposals,
before retries. Rejection and matching review caches reduce actual calls. The
lease default is 3600 seconds to cover these stages; increasing concurrency does
not reduce total model usage. Restart the API and outfit worker after updating
Python configuration fields. This source change does not itself run a paid batch.

### Safe outfit error diagnostics

Apply `sql/migrations/010_outfit_error_diagnostics.sql` **before restarting the outfit worker**. This additive migration creates `outfit_model_calls.diagnostics`; it does not requeue jobs. Failed jobs also carry `stats.error_diagnostics`. Call records distinguish clothing generation, footwear selection, footwear review, and full outfit review. HTTP failures retain status, an allowlisted provider code (otherwise `unknown`), and a validated request ID. Exception messages, response bodies, prompts, credentials, and image URLs are excluded. Existing failed calls cannot be retroactively diagnosed. Retry behavior is unchanged; applying this migration does not retry the 145 failed jobs.

### Yoga pants taxonomy

`Activewear / Yoga Pants` covers yoga-specific fitted, straight, flared and wide-leg pants. `Workout Leggings` remains for general exercise leggings. The existing `fit` field carries silhouette (`Skinny`, `Straight-leg`, `Flared`, `Wide-leg`) and is included in embedding input and visual outfit context. Yoga pants occupy a bottom slot in outfits; wide-leg/flared pairs cannot serve as a leggings-like lower inner layer. Explicit yoga subtype labels normalize to Activewear, but ordinary casual pants are not automatically relabeled. iOS reads the subtype list from the backend taxonomy. No schema migration or automatic relabeling of existing garments is included. Updated outfit prompts change generation/evaluation keys: an active/restarted outfit worker can enqueue work for the new version; keep it stopped if generation should remain paused.

If item deletion fails with `23503` on `outfit_model_calls_job_id_fkey`, apply migration `011_outfit_call_job_delete.sql`. Garment deletion already cascades to build jobs; model call history now survives with a null job reference. Run ownership and usage/cost counters remain intact. In-flight calls may finish after deletion, but new calls still require a valid job lease and stale outfit publication remains guarded. Interrupted detached calls become `unknown` through normal recovery rather than being counted as free. Applying this migration does not delete any garments or restart failed tasks.

### Recognition failure and label confirmation

Queued image recognition requires vision; unavailable/failed vision no longer completes with filename heuristics. The existing durable queue retries failures up to its configured attempt limit. Item state remains `queued`/`Analyzing` during retries, then becomes `failed`/`Recognition Failed`. Safe error details are stored in `recognition_jobs.last_error` and item metadata without raw exception messages or URLs. Opening pending, failed, heuristic-fallback or uncategorized cards does not confirm placeholder labels; explicit manual edits remain supported. Existing completed fallback records are not automatically reset or retried by this change. Restart API and recognition worker and rebuild iOS to activate; no database migration is required for this change.

### Current pipeline: combined accessory selection (supersedes independent shoe review)

With `accessory_pipeline=true`, the stages are clothing generation, **one combined shoe/accessory selection per proposal**, then **one whole-outfit visual review**. No independent shoe review is called. Exactly one suitable shoe is required; hats, scarves, sunglasses and bags are optional and are published only when the whole-outfit review finds clear improvement over the core including shoes. An unsuitable shoe rejects the core; an unhelpful optional accessory can be omitted without rejecting a good core. Hosiery/required clothing coverage stays in the clothing stage.

`footwear_selection_model` controls the combined selector; `accessory_selection_prompt` and `accessory_catalog_limit` control its prompt and non-shoe shortlist. `footwear_catalog_limit` still controls shoes. Maximum calls at eight proposals are `1 + 8 * 2 = 17` before retries, versus 25 previously; this is a call-count reduction, not a guaranteed cost reduction. Previous run snapshots retain `accessory_pipeline=false` and the historical path. No new migration is needed beyond existing diagnostics migration 010. Restarting the outfit worker loads the new configuration and can automatically queue the new version for enrolled users; no worker is started by changing source files.
## Taste learning workers

Apply `sql/migrations/017_taste_profile_learning.sql`, then
`sql/migrations/018_free_text_taste_summary.sql`. Run the deterministic projector with
`make taste-profile-worker`. Optional feedback notes are summarized by a separate
`make free-text-taste-worker` process only after 10 pending notes; each call handles at
most 50 notes and writes provider usage to `taste_summary_runs`. Submitting feedback
does not call a model, and neither worker regenerates previously completed outfits.

Outfit generation receives explicit soft Taste guidance and enforces one exploration
proposal in the normal eight-proposal request. Final image review receives the same
clothing Taste context. Shoe, bag and accessory preferences are retained only as raw
evidence in this release and do not affect personalization.
