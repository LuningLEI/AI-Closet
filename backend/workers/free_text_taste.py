"""Low-frequency worker for optional free-text taste summaries."""
import argparse
import signal
import threading

from app.core.observability import log_event
from app.repositories.factory import build_closet_repository
from app.outfits.store import build_store
from app.services.free_text_taste_summary import FreeTextTasteSummaryService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=30)
    args = parser.parse_args()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    service = FreeTextTasteSummaryService(build_store(build_closet_repository()))
    log_event("free_text_taste_worker.started")
    while not stop.is_set():
        try:
            for uid in service.pending_users():
                service.summarize_user(uid)
                log_event("free_text_taste_worker.summarized", user_id=uid)
            if args.once:
                return
        except Exception as error:
            log_event("free_text_taste_worker.retry", error_type=type(error).__name__)
            if args.once:
                raise
        stop.wait(args.poll_seconds)


if __name__ == "__main__":
    main()
