"""Reset one user's recognition results and requeue their stored images. Stop workers first."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from app.core.config import settings
from app.core.constants import DEFAULT_CATEGORY, PIPELINE_NAME, RecognitionSource, RecognitionStatus
from app.models.domain import ClothingItemRecord, RecognitionJobRecord, utc_now_iso
from app.repositories.base import ClosetRepositoryProtocol
from app.repositories.factory import build_closet_repository


RESET_FIELDS = (
    "analysis_version", "taxonomy_version", "feature_version", "category", "subtype", "color",
    "season", "style", "occasion", "material", "pattern", "fit", "length", "sleeve_length",
    "neckline", "layering_role", "warmth_level", "formality_score", "recognition_status",
    "recognition_source", "recognition_summary", "recognition_confidence", "recognition_tags",
    "feature_vector", "semantic_vector",
)


def reset_user_recognition(
    repository: ClosetRepositoryProtocol,
    user_id: str,
    *,
    dry_run: bool = False,
    include_manual: bool = False,
    limit: int | None = None,
    backup_dir: Path | None = None,
) -> dict:
    if not user_id.strip():
        raise ValueError("A nonempty user_id is required.")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive.")
    items = sorted(repository.list_items_for_recognition_reset(user_id), key=lambda item: (item.created_at, item.id))
    jobs = repository.list_recognition_jobs(user_id)
    if any(row.user_id != user_id for row in [*items, *jobs]):
        raise ValueError("Repository returned records belonging to another user.")
    selected = []
    skipped = Counter()
    for item in items:
        manual = (item.recognition_status == RecognitionStatus.MANUAL
                  or item.recognition_source == RecognitionSource.MANUAL_EDIT
                  or (item.metadata or {}).get("manual_override"))
        if manual and not include_manual:
            skipped['manual'] += 1
        elif not item.image_path and not item.image_url.startswith('https://'):
            skipped['missing_image_reference'] += 1
        elif limit is not None and len(selected) >= limit:
            skipped['limit'] += 1
        else:
            selected.append(item)
    selected_ids = {item.id for item in selected}
    previous_jobs = [job for job in jobs if job.clothing_item_id in selected_ids]
    processing = [job.id for job in previous_jobs if job.status == RecognitionStatus.PROCESSING]
    report = dict(user_id=user_id, dry_run=dry_run,
                  mode="reset-all" if include_manual else "keep-manual", selected=len(selected),
                  item_ids=[item.id for item in selected], skipped=dict(skipped),
                  processing_jobs=len(processing), queued_item_ids=[])
    if dry_run or not selected:
        return report
    if processing:
        raise ValueError("Selected items have processing jobs. Stop workers and let in-flight jobs finish or expire before resetting.")

    run_id = str(uuid4())
    folder = (backup_dir or settings.data_dir / 'recognition_resets') / run_id
    folder.mkdir(parents=True, mode=0o700)
    backup = folder / 'before.json'
    backup.write_text(json.dumps(dict(user_id=user_id, created_at=utc_now_iso(),
                                     items=[item.model_dump() for item in selected],
                                     jobs=[job.model_dump() for job in previous_jobs]), indent=2))
    backup.chmod(0o600)
    report['backup'] = str(backup.resolve())
    report['run_id'] = run_id
    report['queued_job_ids'] = {}
    report['enqueue_complete'] = False
    progress = folder / 'result.json'

    def save_progress():
        temporary = folder / 'result.tmp'
        temporary.write_text(json.dumps(report, indent=2))
        temporary.replace(progress)

    save_progress()

    for item in selected:
        old_jobs = [job for job in previous_jobs if job.clothing_item_id == item.id]
        old_jobs.sort(key=lambda job: (job.created_at, job.id))
        filename = (old_jobs[-1].filename if old_jobs else
                    Path(urlsplit(item.image_path or item.image_url).path).name or 'stored-image.jpg')
        fresh = ClothingItemRecord(user_id=user_id, image_url=item.image_url, category=DEFAULT_CATEGORY).model_dump()
        updates = {key: fresh[key] for key in RESET_FIELDS}
        updates.update(recognition_status=RecognitionStatus.QUEUED,
                       recognition_source=RecognitionSource.ANALYZING,
                       recognition_summary='Queued for recognition with the current model settings.',
                       metadata={**(item.metadata or {}), 'pipeline': PIPELINE_NAME,
                                 'recognition_status': RecognitionStatus.QUEUED,
                                 'manual_override': False, 'occasion_overrides': {'added': [], 'removed': []},
                                 'recognition_reset_id': run_id})
        try:
            # The CLI is an offline maintenance command: all worker/writer processes must be stopped.
            repository.delete_recognition_jobs_for_item(item.id, user_id)
            if repository.update_item(item.id, updates, user_id) is None:
                raise RuntimeError('Item disappeared during reset.')
            created_job = repository.create_recognition_job(RecognitionJobRecord(
                user_id=user_id, clothing_item_id=item.id, filename=filename,
                image_url=item.image_url, image_path=item.image_path,
            ))
            report['queued_item_ids'].append(item.id)
            report['queued_job_ids'][item.id] = created_job.id
        except Exception as error:
            report['failed_item_id'] = item.id
            report['error_type'] = type(error).__name__
            # Best-effort per-item rollback, including a possibly successful insert with a lost response.
            try:
                repository.delete_recognition_jobs_for_item(item.id, user_id)
                original = item.model_dump()
                if repository.update_item(item.id, {key: original[key] for key in (*RESET_FIELDS, 'metadata')}, user_id) is None:
                    raise RuntimeError('Item missing during rollback.')
                for job in old_jobs:
                    repository.create_recognition_job(job)
                report['rollback'] = 'restored_failed_item'
            except Exception:
                report['rollback'] = 'failed; use before.json to recover this item before restarting workers'
            save_progress()
            raise RuntimeError(f'Reset stopped at item {item.id}. Completed items remain queued. Report: {progress.resolve()}') from error
        save_progress()
    report['enqueue_complete'] = True
    save_progress()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', required=True, type=UUID, help='User UUID; always required, never all users.')
    parser.add_argument('--dry-run', action='store_true', help='List affected item IDs without writing anything.')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--keep-manual', dest='include_manual', action='store_false',
                      help='Keep manually corrected items unchanged; reset the remaining items (default).')
    mode.add_argument('--include-manual', dest='include_manual', action='store_true',
                      help='Reset all items, including manually corrected clothing attributes.')
    parser.set_defaults(include_manual=False)
    parser.add_argument('--limit', type=int, help='Reset only this many eligible items, oldest first.')
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error('--limit must be positive')
    try:
        report = reset_user_recognition(build_closet_repository(), str(args.user_id),
                                        dry_run=args.dry_run, include_manual=args.include_manual, limit=args.limit)
    except Exception as error:
        # Do not print backend exception payloads, keys, or signed image URLs.
        message = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
        print(f'Reset failed: {message}')
        return 1
    print(json.dumps(report, indent=2))
    if not args.dry_run and report['queued_item_ids']:
        print('Restart the worker with the desired model configuration: python -m workers.recognition')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
