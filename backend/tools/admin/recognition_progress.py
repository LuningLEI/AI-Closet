"""Read-only progress for one recognition-reset batch; optionally watch until it finishes."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from uuid import UUID

from app.core.config import settings
from app.repositories.factory import build_closet_repository


def find_run(root: Path, user_id: str, run_id: str | None = None) -> Path:
    candidates = [root / run_id / 'result.json'] if run_id else list(root.glob('*/result.json'))
    matching = []
    for path in candidates:
        if not path.exists():
            continue
        report = json.loads(path.read_text())
        if report.get('user_id') == user_id:
            backup = json.loads((path.parent / 'before.json').read_text())
            matching.append((datetime.fromisoformat(backup['created_at']), path))
    if not matching:
        raise ValueError('No reset batch found for this user on this machine.')
    return max(matching, key=lambda pair: pair[0])[1]


def batch_progress(repository, user_id: str, path: Path) -> dict:
    report = json.loads(path.read_text())
    backup = json.loads((path.parent / 'before.json').read_text())
    if report['user_id'] != user_id or backup['user_id'] != user_id:
        raise ValueError('Reset batch belongs to another user.')
    jobs = repository.list_recognition_jobs(user_id)
    jobs_by_id = {job.id: job for job in jobs if job.user_id == user_id}
    counts = Counter(dict(complete=0, queued=0, processing=0, retrying=0, failed=0, missing=0, unknown=0))
    queued = report['queued_item_ids']
    for item_id in queued:
        if 'queued_job_ids' in report:
            job = jobs_by_id.get(report['queued_job_ids'].get(item_id))
            if job is not None and job.clothing_item_id != item_id:
                job = None
        else:
            # Compatibility with batches created before explicit job IDs were recorded.
            # Match only jobs inserted during that reset, never a subsequent re-recognition.
            start = datetime.fromisoformat(backup['created_at'])
            end = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            previous_ids = {row['id'] for row in backup['jobs']}
            matches = [job for job in jobs_by_id.values()
                       if job.clothing_item_id == item_id and job.id not in previous_ids
                       and start <= datetime.fromisoformat(job.created_at) <= end]
            job = matches[0] if len(matches) == 1 else None
        if job is None:
            counts['missing'] += 1
        elif job.status == 'failed':
            counts['retrying' if job.attempts < settings.recognition_worker_max_attempts else 'failed'] += 1
        elif job.status == 'dead_letter':
            counts['failed'] += 1
        elif job.status in {'complete', 'queued', 'processing'}:
            counts[job.status] += 1
        else:
            counts['unknown'] += 1
    not_queued = max(0, report['selected'] - len(queued))
    enqueue_complete = report.get('enqueue_complete', not not_queued and not report.get('failed_item_id'))
    pending = counts['queued'] + counts['processing'] + counts['retrying']
    success = enqueue_complete and not not_queued and counts['complete'] == report['selected']
    issues = counts['failed'] + counts['missing'] + counts['unknown'] + not_queued
    if success:
        state = 'complete'
    elif pending or (not enqueue_complete and not report.get('failed_item_id')):
        state = 'running'
    else:
        state = 'needs_attention'
    return dict(run_id=path.parent.name, total=report['selected'], **counts,
                not_queued=not_queued, state=state, issues=issues)


def format_progress(result: dict) -> str:
    message = (f"完成 {result['complete']}/{result['total']} | 待处理 {result['queued']} | "
               f"识别中 {result['processing']} | 等待重试 {result['retrying']} | "
               f"最终失败 {result['failed']} | 任务缺失 {result['missing']} | "
               f"未入队 {result['not_queued']} | 未知状态 {result['unknown']}")
    if result['state'] == 'complete':
        message += '\n本次重置批次已全部处理完成。'
    elif result['state'] == 'needs_attention':
        message += '\n本批次需要处理异常，不能认定为全部完成。'
    return message


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', type=UUID, required=True)
    parser.add_argument('--run-id', type=UUID, help='Default: latest reset for this user on this machine.')
    parser.add_argument('--watch', action='store_true', help='Refresh every 5 seconds; exit when finished or blocked.')
    args = parser.parse_args(argv)
    try:
        # Pin the batch once: a later reset must not silently change what is being monitored.
        path = find_run(settings.data_dir / 'recognition_resets', str(args.user_id), str(args.run_id) if args.run_id else None)
        repository = build_closet_repository()
        print(f'重置批次：{path.parent.name}', flush=True)
        while True:
            result = batch_progress(repository, str(args.user_id), path)
            print(format_progress(result), flush=True)
            if result['state'] != 'running' or not args.watch:
                return 2 if result['state'] == 'needs_attention' else 0
            time.sleep(5)
    except KeyboardInterrupt:
        print('\n已停止查看；不会停止 worker。')
        return 0
    except Exception as error:
        print(f'Progress lookup failed: {type(error).__name__}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
