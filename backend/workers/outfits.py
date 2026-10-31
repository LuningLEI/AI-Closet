"""Concurrent durable outfit worker; each consumer owns its database client."""
import argparse
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from app.repositories.factory import build_closet_repository
from app.outfits.config import load_config
from app.outfits.store import build_store
from app.outfits.service import OutfitLibrary
from app.core.observability import log_event


def error_summary(error):
    """Expose actionable codes without logging provider bodies, URLs or credentials."""
    import re
    code = str(getattr(error, 'code', '') or '')
    code = code if re.fullmatch(r'[A-Z0-9]{3,12}', code) else 'unknown'
    summary = f'type={type(error).__name__} code={code}'
    from app.outfits.diagnostics import error_details
    summary += ''.join(f' {key}={value}' for key,value in error_details(error).items() if key != 'type')
    from pydantic import ValidationError
    if isinstance(error, ValidationError):
        # Do not print rejected values, messages or context: these may contain images/tokens.
        fields = []
        for detail in error.errors(include_input=False, include_url=False, include_context=False)[:8]:
            location = '.'.join(str(part) for part in detail['loc']) or 'root'
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', location):
                location = 'redacted'
            kind = detail['type']
            if not re.fullmatch(r'[a-z_]{1,80}', kind):
                kind = 'unknown'
            fields.append(f'{location}:{kind}')
        summary += ' fields=' + ','.join(fields)
        summary += ' action=restart_worker_after_code_changes_then_check_reported_fields'
    if code in {'PGRST202', 'PGRST204', 'PGRST205', '42P01', '42703', '42883'}:
        summary += ' action=apply_database_migrations_008_then_009_and_refresh_PostgREST_schema_cache'
    elif code in {'42501', 'PGRST301', 'PGRST302', 'PGRST303'}:
        summary += ' action=check_backend_database_credentials_and_permissions'
    return summary


def process_next(library):
    library.store.recover_calls()
    job = library.store.claim(library.config)
    if not job:
        return False
    log_event('outfit_job.started', job_id=job['id'], anchor_item_id=job['anchor_item_id'], attempt=job['attempts'])
    try:
        library.process(job)
        library.refresh_projection(job['user_id'])
        log_event('outfit_job.finished', job_id=job['id'])
    except Exception as error:
        log_event('outfit_job.failed', job_id=job['id'], error=error_summary(error))
    return True


def consume(stop):
    # HTTP/database clients are not shared between consumer threads.
    repo = None
    store = None
    while not stop.is_set():
        delay = 5
        try:
            config = load_config()
            delay = config.poll_seconds
            if repo is None:
                repo = build_closet_repository()
                store = build_store(repo)
            if process_next(OutfitLibrary(repo, store, config)):
                continue
        except Exception as error:
            # A temporary DB/config error must not silently kill a consumer.
            log_event('outfit_worker.retry', error=error_summary(error))
        stop.wait(delay)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true', help='Reconcile and process at most one anchor, regardless of concurrency')
    parser.add_argument('--concurrency', type=int, default=3, help='Concurrent anchor tasks (1-8; default: 3)')
    parser.add_argument('--user-id', help='Enroll and enqueue this user’s current ready clothes')
    parser.add_argument('--anchor-item-id', help='Queue one ready item with --user-id')
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--enqueue-only', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 8:
        parser.error('--concurrency must be between 1 and 8')
    if (args.anchor_item_id or args.retry_failed or args.enqueue_only) and not args.user_id:
        parser.error('These options require --user-id')
    repo = build_closet_repository()
    store = build_store(repo)
    config = load_config()
    library = OutfitLibrary(repo, store, config)
    if args.user_id:
        print(library.build(args.user_id, args.anchor_item_id, args.retry_failed), flush=True)
    if args.enqueue_only:
        return
    if args.once:
        for uid in store.users():
            library.sync(uid)
            library.refresh_projection(uid)
        process_next(library)
        return

    stop = threading.Event()
    def stop_gracefully(signum, frame):
        if not stop.is_set():
            log_event('outfit_worker.stopping', behavior='finish_active_tasks')
        stop.set()
    previous = {sig: signal.signal(sig, stop_gracefully) for sig in (signal.SIGINT, signal.SIGTERM)}
    log_event('outfit_worker.started', concurrency=args.concurrency)
    try:
        with ThreadPoolExecutor(max_workers=args.concurrency, thread_name_prefix='outfit') as pool:
            consumers = [pool.submit(consume, stop) for _ in range(args.concurrency)]
            try:
                while not stop.is_set():
                    delay = 5
                    try:
                        config = load_config()
                        delay = config.poll_seconds
                        library = OutfitLibrary(repo, store, config)
                        for uid in store.users():
                            if stop.is_set():break
                            library.sync(uid)
                            library.refresh_projection(uid)
                    except Exception as error:
                        log_event('outfit_worker.reconcile_retry', error=error_summary(error))
                    for future in consumers:
                        if future.done():
                            future.result()
                            raise RuntimeError('Outfit consumer exited unexpectedly')
                    stop.wait(delay)
            finally:
                stop.set()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
