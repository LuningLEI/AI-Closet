from __future__ import annotations

import argparse
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.core.observability import log_event
from app.core.config import settings
from app.repositories.factory import build_closet_repository
from app.services.recognition_pipeline import RecognitionPipeline


def run_worker(once: bool = False, *, stop: threading.Event | None = None) -> None:
    managed_stop = stop is not None
    stop = stop or threading.Event()
    def pause(seconds: float) -> None:
        if managed_stop:
            stop.wait(seconds)
        else:
            time.sleep(seconds)
    repository = build_closet_repository()
    pipeline = RecognitionPipeline(repository)
    log_event(
        "recognition_worker.started",
        batch_size=settings.recognition_worker_batch_size,
        max_attempts=settings.recognition_worker_max_attempts,
        poll_seconds=settings.recognition_worker_poll_seconds,
        once=once,
    )

    while not stop.is_set():
        try:
            jobs = repository.claim_recognition_jobs(
                batch_size=settings.recognition_worker_batch_size,
                max_attempts=settings.recognition_worker_max_attempts,
            )
        except Exception as error:
            log_event("recognition_worker.claim_failed", error=str(error))
            if once:
                raise
            pause(max(1, settings.recognition_worker_poll_seconds))
            continue
        if jobs:
            log_event("recognition_worker.claimed", count=len(jobs))
            for job in jobs:
                log_event(
                    "recognition_worker.job_started",
                    job_id=job.id,
                    user_id=job.user_id,
                    attempts=job.attempts,
                    filename=job.filename,
                )
                started_at = time.monotonic()
                try:
                    pipeline.process_job(job)
                except Exception as error:
                    # The database may also be unavailable while recording a failure.
                    # Leave the persisted lease for reclamation instead of losing the worker.
                    log_event("recognition_worker.processing_interrupted", job_id=job.id, error=str(error))
                    if once:
                        raise
                    continue
                log_event(
                    "recognition_worker.job_finished",
                    job_id=job.id,
                    elapsed_ms=round((time.monotonic() - started_at) * 1000, 2),
                )
        elif once:
            log_event("recognition_worker.empty")
            return

        if once:
            return
        pause(settings.recognition_worker_poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Process queued AI Closet recognition jobs.")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit.")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="Independent recognition consumers (1-8; default: 1).")
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 8:
        parser.error("--concurrency must be between 1 and 8")
    if args.once and args.concurrency != 1:
        parser.error("--once requires --concurrency 1")
    if args.once:
        run_worker(once=True)
        return
    stop = threading.Event()
    def stop_gracefully(_signum, _frame):
        stop.set()
    previous = {sig: signal.signal(sig, stop_gracefully) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        with ThreadPoolExecutor(max_workers=args.concurrency, thread_name_prefix="recognition") as pool:
            consumers = [pool.submit(run_worker, stop=stop) for _ in range(args.concurrency)]
            while not stop.is_set():
                stop.wait(1)
            for consumer in consumers:
                consumer.result()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    main()
