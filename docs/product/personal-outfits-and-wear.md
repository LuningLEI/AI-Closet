# Saved-outfit recommendations and wear history

Today, Recommendations and the chat recommendation skill rank **saved outfits**, rather than building new combinations from the closet at request time. Outfit generation is a separate worker workflow. An empty eligible library returns no recommendations; there is no hidden fallback that defeats recent-wear exclusion.

## Data and ownership

`personal_outfits` stores a user ID, a deterministic ID derived from user + sorted member IDs, a title and member IDs. Re-saving the same composition is idempotent. Replacing a garment creates/saves a distinct composition; it does not mutate the source generated outfit or claim a new AI visual review. Manual compositions are shown as “Saved by you.” Saving is explicit user approval, so personal outfits enter ranking exactly as saved without a system structure, shoe, layering or aesthetic veto.

Personal outfits are separate from `current_outfits` and historical `outfits`; generation refreshes cannot erase them. The library SQL query combines them with current generated outfits, deduplicates identical core membership, supports pagination and filters by any member. An outfit with a deleted member is hidden. Current garment labels and photos are used at read/scoring time. Generated outfits retain system validation; personal outfits follow the user's saved decision.

`outfit_wear_events` records an idempotency UUID, user ID, the actual worn item IDs and a timezone-aware timestamp. Optional layers only count when the user records that displayed combination. Ownership is checked in the API and in service-role database RPCs; both tables use owner-read RLS. The API supports deleting a wear event for undo. Historical events retain IDs even when a garment is later deleted.

## Ranking

1. Load the user's saved personal outfits and generated outfits whose visible review status is passed. Include approved optional variants as separate ranking candidates, without changing the library's core/optional representation.
2. Resolve current owned garments and discard missing members. Deduplicate exact item sets.
3. If **any member**, including shoes/accessories, was worn less than 48 hours ago, exclude the candidate. Never relax this rule to fill a result list. With a small shoe collection this may legitimately yield no results.
4. Reuse context scoring for weather, occasion, style, color, completeness and semantic fit. Image models are not called. A text embedding may be requested when item embeddings are available.
5. Subtract the recent-wear penalty and rank/diversify. Return `original_score`, `wear_penalty`, `score` and `outfit_id`.

Policy lives in `backend/app/outfits/recommendation_policy.json`:

- Exclusion: 2 days, measured as elapsed 48 hours, not calendar dates.
- Penalty at day 2: 40 points.
- Half-life: 3 days after exclusion (day 5: 20; day 8: 10).
- Cutoff: day 14, penalty 0.
- Use the most recent wear among all members (maximum individual penalty), not a sum. This avoids penalizing a five-piece outfit more simply because it has more pieces. Repeated wears reset the clock without unlimited accumulation.

The penalty does not alter saved aesthetic judgments. Scores are floored at zero. The existing context scorer ranks suitability; it is not a new visual-quality evaluation or a strict temperature safety filter.

## iOS

- Closet → Outfits → `+`: select garments from category filters, preview and save.
- Library detail, optional combinations, Today, Recommendations and chat outfit cards share replacement/wear actions.
- Replacement editor lets users remove/add/replace garments and save a new personal outfit. The original remains intact.
- `Wear it today` persists the daily selection and a wear event. Reopening the card shows the latest worn time. For today's selected outfit, the action becomes `Remove from today`; Today and Recommendations refresh after either action. Wear requests reuse an event ID when retrying an uncertain response.
- Manual save and replacement do not enqueue recognition or outfit model generation.

## Rollout and validation

Apply all ordered migrations through 019, restart the API and workers from the same release, and rebuild iOS. No model call is required for manual outfit saves or wear scoring.

Tests cover user isolation, duplicate compositions, item-level lookup, deleted-member hiding, wear idempotency/undo, future timestamps, exact 48-hour and 14-day boundaries, decay, shared-item exclusion and no generation fallback. Migration tests run in disposable PostgreSQL with pgvector fields substituted by arrays solely because pgvector is not installed in that test server.

Limitations: reading all eligible saved combinations for ranking remains linear in library size; the library display itself retains SQL pagination. A large-scale deployment should shortlist by context in SQL and aggregate latest wear by item. No user-study evidence yet establishes the default 40-point penalty or 3-day half-life as optimal.
