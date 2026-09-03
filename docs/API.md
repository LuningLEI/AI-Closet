# API Contract

The backend is the source of truth for the API contract. FastAPI generates OpenAPI from the route definitions and Pydantic request/response models.

## Generated Files

| File | Purpose |
| --- | --- |
| `docs/api/openapi.json` | Versioned OpenAPI contract exported from FastAPI. |
| `web/lib/generated/api-types.ts` | Generated TypeScript types for the web client. |

## Commands

Export the backend contract:

```bash
make export-openapi
```

Generate web TypeScript types:

```bash
make web-api-types
```

Run both:

```bash
make api-contract
```

## Workflow

1. Change backend routes or Pydantic models.
2. Run `make api-contract`.
3. Review changes in `docs/api/openapi.json` and `web/lib/generated/api-types.ts`.
4. Update web or iOS client usage if the contract changed.

## Auth Contract

Read endpoints use the authenticated Supabase user when an `Authorization: Bearer <supabase-jwt>` header is present.

Mutation endpoints require a real authenticated user when `REQUIRE_AUTH_FOR_MUTATIONS=true`:

- `PATCH /api/v1/preferences`
- `POST /api/v1/profile/avatar`
- `PATCH /api/v1/items/{item_id}`
- `DELETE /api/v1/items/{item_id}`
- `POST /api/v1/items/upload`
- `POST /api/v1/items/upload-batch`

Local JSON-file demos may set `REQUIRE_AUTH_FOR_MUTATIONS=false`, but Supabase-backed web and iOS clients should keep it enabled.

## Storage Contract

Images are private storage objects. API responses expose short-lived signed URLs in `image_url`; clients should not persist those URLs as permanent asset IDs.

Use `image_path` as the stable private object reference and call the owning API again to refresh image URLs.

`GET /api/v1/storage/signed-url-contract` returns the signed URL expiry and refresh guidance for web/iOS clients.

## Upload Queue Contract

Upload endpoints create the closet card immediately with `recognition_status=queued` and `recognition_source=Analyzing`.

`POST /api/v1/items/upload-batch` returns:

- `items`: cards created immediately
- `queued`: queue status for each created item
- `errors`: per-file failures

Clients should show loading state on the item card until the worker updates `recognition_status` to `complete`, `failed`, or `dead_letter`.

## Operational Endpoints

`GET /api/v1/health` is the production health check endpoint. It returns:

```json
{"status":"ok"}
```

`GET /api/v1/admin/queue/health` returns recognition queue health for the authenticated user:

- total jobs
- status counts
- oldest queued timestamp
- processing count
- dead-letter count
- recent failed/dead-letter errors

This endpoint is intended for debugging worker health without exposing image contents.

## iOS Direction

The same `docs/api/openapi.json` file can later be used to generate a Swift client with OpenAPI Generator, so the iOS app does not need a manually duplicated API layer.
