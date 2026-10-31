"""Bounded retries for read-only database requests; never replay writes."""
import time
import httpx


class DatabaseReadUnavailable(RuntimeError):
    pass


def execute_read(build_request):
    for attempt in range(3):
        try:
            return build_request().execute()
        except (httpx.TransportError,) as error:
            if attempt == 2:
                raise DatabaseReadUnavailable('Database read temporarily unavailable') from error
            time.sleep(0.2 * (2 ** attempt))
