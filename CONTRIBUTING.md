# Contributing

This repo is organized as a small production-style monorepo. Keep changes scoped, documented, and easy for another engineer to review.

## Branches

Use short feature branches:

```text
feature/profile-preferences
fix/upload-queue-status
docs/local-runbook
```

## Before Opening a Pull Request

Run the relevant checks:

```bash
make backend-check
make web-build
```

For iOS source changes, build the Xcode project from `ios/`.

## Code Ownership

- `web/`: React components, UI state, Supabase client auth, browser workflows.
- `backend/`: API contracts, repository layer, recognition worker, recommendation logic.
- `ios/`: native iOS app, Swift services, local ML experiments.
- `docs/`: architecture, setup, operational notes.

## Secrets

Never commit local environment files or generated signed URLs. Keep examples in `.env.example` files only.

## Style

- Prefer small modules with explicit responsibilities.
- Keep API contracts in typed models.
- Keep user data scoped by authenticated `user_id`.
- Add a short doc note when changing setup, schema, queues, or deployment behavior.
