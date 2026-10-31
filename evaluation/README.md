# Evaluation workspace

This directory contains local inputs and generated artifacts. Evaluation code
lives in `backend/tools/evaluation/`; production code must never import files
from this directory.

| Domain | Directory | Contents |
|---|---|---|
| Recognition | `recognition/single_occasion/` | Original single-occasion annotations and analysis |
| Recognition | `recognition/multi_occasion/` | Multi-occasion annotations, score snapshots, and analysis |
| Recognition | `recognition/audit-YYYYMMDD/` | Date-scoped recognition audits |
| Outfits | `outfits/comparison_runs/<run-id>/` | Model and pipeline comparison runs |
| Outfits | `outfits/library_pilot/` | Human outfit-library annotations and provenance |
| Taste | `taste/simulation/` | Default-parameter learning simulations |
| Taste | `taste/parameter_search/` | Parameter search and validation results |
| Taste | `taste/before_after/<date>/` | Paired pre-learning and post-learning exports |
| Taste | `taste/end_to_end/<date>/` | End-to-end persona evaluation snapshots |

## Storage policy

The root README is versioned. Workbooks, wardrobe photos, caches, model outputs,
SQLite files, and generated reports remain local and are ignored by Git because
they can contain private user data or be reproduced. A result directory should
contain a manifest or configuration snapshot whenever the generating tool
supports one.

Use lower-case snake_case for experiment families, `YYYYMMDD` for date folders,
and immutable run IDs for repeated runs. Temporary Office files (`~$*.xlsx`) and
image caches are disposable and must not be referenced as evaluation evidence.

## Common commands

Run these from `backend/`:

```bash
python -m tools.evaluation.analyze_human_eval \
  --workbook ../evaluation/recognition/multi_occasion/annotation.xlsx \
  --output-dir ../evaluation/recognition/multi_occasion/analysis

python -m tools.evaluation.taste_learning_simulation \
  --runs 100 --steps 120 --output ../evaluation/taste/simulation

python -m tools.evaluation.taste_parameter_search \
  --output ../evaluation/taste/parameter_search
```

Method descriptions belong in [`../docs/evaluation/`](../docs/evaluation/).
Generated outputs belong here.
