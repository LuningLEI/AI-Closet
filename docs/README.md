# Documentation

Documentation is organized by purpose so implementation guides, product policy,
experiments, and operational runbooks do not compete in one flat directory.

| Area | Contents | Start here |
|---|---|---|
| `architecture/` | Current system and database design | [System architecture](architecture/system.md) |
| `product/` | User-visible outfit, feedback, and personalization behavior | [Taste learning pipeline](product/taste-learning-pipeline.md) |
| `evaluation/` | Methodology and parameter-selection explanations | [Taste Profile simulation](evaluation/taste-profile-simulation.md) |
| `operations/` | API contract, local development, and deployment | [Local development](operations/local-development.md) |
| `planning/` | Active work with explicit acceptance criteria | [Active plans](planning/README.md) |
| `changes/` | Shipped behavior and configuration change records | [Taste Profile v2](changes/2026-10-29-taste-profile-v2.md) |
| `api/` | Generated, versioned API contract | [OpenAPI JSON](api/openapi.json) |

Architecture and product documents describe current behavior. Change records
explain a currently deployed decision without replacing runtime configuration as
the source of truth. Generated evaluation artifacts live under
[`../evaluation/`](../evaluation/README.md).
