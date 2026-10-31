"""Show/update a user's per-occasion thresholds and reapply stored scores without model calls."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import UUID, uuid4

from app.core.config import settings
from app.repositories.factory import build_closet_repository
from app.services.occasion_support import effective_occasion, model_occasions
from app.services.occasion_thresholds import user_thresholds, update_user_thresholds, validate_thresholds
from app.services.taxonomy import OCCASIONS


def reapply_user_occasions(repository, user_id: str, *, thresholds=None, dry_run=False, backup_dir: Path | None = None):
    thresholds = thresholds or user_thresholds(repository, user_id)
    counts = Counter()
    changes = []
    items = repository.list_items_for_recognition_reset(user_id)
    for item in items:
        if item.user_id != user_id:
            raise ValueError('Repository returned another user’s item.')
        counts['scanned'] += 1
        if item.recognition_status in {'queued', 'processing'}:
            counts['pending_skipped'] += 1
            continue
        if model_occasions(item, thresholds) is None:
            counts['without_scores_skipped'] += 1
            continue
        value = effective_occasion(item, thresholds)
        if not value:
            counts['manual_empty_preserved'] += 1
        if value != item.occasion:
            changes.append((item, value))
        else:
            counts['unchanged'] += 1
    report = dict(user_id=user_id, thresholds=thresholds, dry_run=dry_run, counts=dict(counts),
                  changes=[{'item_id': item.id, 'before':item.occasion, 'after':value} for item,value in changes],
                  updated=0, conflicts=[])
    if dry_run or not changes:
        return report
    folder=(backup_dir or settings.data_dir/'occasion_reapplications')/str(uuid4())
    folder.mkdir(parents=True,mode=0o700)
    before=folder/'before.json'
    before.write_text(json.dumps({'user_id':user_id,'created_at':datetime.now(timezone.utc).isoformat(),
                                 'thresholds':thresholds,'items':[i.model_dump() for i,_ in changes]},indent=2))
    before.chmod(0o600)
    report['backup']=str(before.resolve())
    try:
        for item,value in changes:
            latest=repository.get_item(item.id,user_id)
            if latest is None or latest.model_dump()!=item.model_dump():
                report['conflicts'].append(item.id)
                continue
            # Only refresh the derived label cache. Scores, overrides, history and images stay intact.
            if repository.update_item(item.id,{'occasion':value},user_id) is None:
                report['conflicts'].append(item.id)
            else:
                report['updated']+=1
            (folder/'result.json').write_text(json.dumps(report,indent=2))
    except Exception:
        report['status']='interrupted'
        (folder/'result.json').write_text(json.dumps(report,indent=2))
        raise RuntimeError(f'Reapplication interrupted; inspect {folder / "result.json"}') from None
    (folder/'result.json').write_text(json.dumps(report,indent=2))
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id',type=UUID,required=True)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--set',action='append',default=[],metavar='OCCASION=VALUE',help='Repeat for multiple occasions.')
    group.add_argument('--reset-defaults',action='store_true',help='Set all this user’s occasion thresholds to 0.8.')
    parser.add_argument('--reapply',action='store_true',help='Refresh current item labels from saved scores; preserve manual overrides.')
    parser.add_argument('--dry-run',action='store_true',help='Preview configuration and item changes without writes.')
    args=parser.parse_args(argv)
    try:
        changes = dict.fromkeys(OCCASIONS,0.8) if args.reset_defaults else {}
        for expression in args.set:
            label,separator,value=expression.partition('=')
            if not separator: raise ValueError('Use --set Occasion=0.8')
            changes[label]=float(value)
        validate_thresholds(changes)
        repository=build_closet_repository()
        user_id=str(args.user_id)
        previous=user_thresholds(repository,user_id)
        current={**previous,**changes}
        if changes and not args.dry_run:
            current=update_user_thresholds(repository,user_id,changes)
        report={'user_id':user_id,'previous_thresholds':previous,'thresholds':current,'dry_run':args.dry_run}
        if args.reapply:
            report['reapplication']=reapply_user_occasions(repository,user_id,thresholds=current,dry_run=args.dry_run)
        print(json.dumps(report,indent=2))
        return 2 if report.get('reapplication',{}).get('conflicts') else 0
    except Exception as error:
        print(f'Threshold operation failed: {error if isinstance(error,(ValueError,RuntimeError)) else type(error).__name__}')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
