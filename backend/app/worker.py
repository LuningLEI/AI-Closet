from __future__ import annotations

import argparse
import time

from app.core.observability import log_event
from app.core.config import settings
from app.repositories.factory import build_closet_repository
from app.services.recognition_pipeline import RecognitionPipeline


def run_worker(once: bool = False) -> None:
    repository = build_closet_repository()
    pipeline = RecognitionPipeline(repository)
    log_event(
        "recognition_worker.started",
        batch_size=settings.recognition_worker_batch_size,
        max_attempts=settings.recognition_worker_max_attempts,
        poll_seconds=settings.recognition_worker_poll_seconds,
        once=once,
    )

    while True:
        jobs = repository.claim_recognition_jobs(
            batch_size=settings.recognition_worker_batch_size,
            max_attempts=settings.recognition_worker_max_attempts,
        )
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
                pipeline.process_job(job)
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
        time.sleep(settings.recognition_worker_poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Process queued AI Closet recognition jobs.")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit.")
    args = parser.parse_args()
    run_worker(once=args.once)


if __name__ == "__main__":
    main()
