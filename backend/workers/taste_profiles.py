"""Low-cost deterministic taste projection worker; performs no model calls."""
import argparse
import signal
import threading

from app.core.observability import log_event
from app.repositories.factory import build_closet_repository
from app.outfits.store import build_store
from app.services.taste_profile_service import TasteProfileService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5)
    args = parser.parse_args()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    service = TasteProfileService(build_store(build_closet_repository()))
    log_event("taste_profile_worker.started")
    while not stop.is_set():
        try:
            users = service.pending_users()
            for uid in users:
                service.reduce_user(uid)
                log_event("taste_profile_worker.projected", user_id=uid)
            if args.once:
                return
        except Exception as error:
            log_event("taste_profile_worker.retry", error_type=type(error).__name__)
            if args.once:
                raise
        stop.wait(args.poll_seconds)


if __name__ == "__main__":
    main()
