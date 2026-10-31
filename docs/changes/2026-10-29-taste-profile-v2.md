# Taste Profile v2 Production Default Promotion

Date: 2026-10-29
Algorithm: `taste-profile-v1` → `taste-profile-v2`

## Reason

A paired two-stage Monte Carlo simulation searched 48 parameter combinations, then validated the top six plus the v1 default with 30 synthetic users per scenario. The selected configuration ranked first under the pre-registered composite objective covering stable ranking, 20% noisy feedback, preference drift, regret, score saturation, coverage, and activation speed.

## Production changes

| Parameter | v1 | v2 |
|---|---:|---:|
| Evidence threshold | 3 | 2 |
| Exploration rate | 10% | 15% |
| Preference half-life | 180 days | 270 days |
| Decay floor | 30% | 0% |
| Prior strength | 5.0 | 2.5 |
| Personalization scale | 4.0 | 0.5 |

Signal strengths remain unchanged: Personal Outfit +2.0, Wear +1.5, Like +1.0, reason-scoped Not for Me −1.0. The ±20 maximum personalization bound also remains unchanged.

## Simulation evidence

| Stable scenario | v1 | v2 |
|---|---:|---:|
| Mean NDCG@10 | 0.149 | 0.459 |
| Mean regret | 2.786 | 1.646 |
| Final score saturation | 100% | 0% |
| Average activation opportunity | 5.2 | 3.7 |

Under preference drift, mean NDCG@10 increased from 0.148 to 0.273, while recovery to 0.50 feature alignment slowed from 31.3 to 57.4 feedback opportunities. This trade-off must be monitored with real feedback.

## Deployment behavior

- Migration `019_taste_profile_v2_defaults.sql` changes the database default and increments `source_version` for older projections.
- `taste_profile_worker` deterministically replays existing immutable feedback, wear, and personal-outfit snapshots.
- The API also detects an old algorithm version and lazily rebuilds it if the worker has not done so.
- Reprojection makes no model calls and does not modify feedback, outfits, wear history, explicit preferences, or clothing labels.

## Rollback

Restore the v1 constants in `backend/app/services/taste_profile.py`, assign a new algorithm version rather than reusing `taste-profile-v1`, and mark affected profiles dirty by incrementing `source_version`. Do not delete feedback or profile history.

## Evidence files

- `evaluation/taste/parameter_search/report.zh-CN.md`
- `evaluation/taste/parameter_search/validation_ranking.csv`
- `evaluation/taste/parameter_search/recommended_config.json`
