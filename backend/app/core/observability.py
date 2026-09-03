from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Request, Response


REQUEST_ID_HEADER = "x-request-id"


def log_event(event: str, **payload) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **payload,
            },
            default=str,
            sort_keys=True,
        )
    )


async def observe_request(request: Request, call_next) -> Response:
    request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
    started_at = time.monotonic()
    status_code = 500
    response: Response | None = None

    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    except asyncio.CancelledError:
        log_event(
            "http.request_cancelled",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        raise
    except Exception as error:
        log_event(
            "http.request_failed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            error=type(error).__name__,
        )
        raise
    finally:
        elapsed_ms = round((time.monotonic() - started_at) * 1000, 2)
        log_event(
            "http.request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
        )
