"""Replace the garment occasion vector column with unmodified saved model scores."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path

from openpyxl import load_workbook

from tools.evaluation.fill_multi_occasion_baselines import write_cells
from app.repositories.factory import build_closet_repository
from app.services.occasion_support import select_scored_occasions
from app.services.taxonomy import OCCASIONS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workbook', type=Path, required=True)
    parser.add_argument('--user-id', required=True)
    args = parser.parse_args()
    source = args.workbook
    output = source.with_name('closet_outfit_annotation_current_recognition.xlsx')
    if output.exists():
        raise FileExistsError(f'Output already exists: {output}')
    sheet = load_workbook(source)['Garment Labels']
    assert sheet['H2'].value == 'baseline-vector', 'Unexpected occasion column'
    repository = build_closet_repository()
    items = {item.id: item for item in repository.list_items_for_recognition_reset(args.user_id)}
    cells = {'H2': 'current-recognition-model'}
    records = []
    for row in range(3, sheet.max_row + 1):
        code, item_id = sheet.cell(row, 2).value, sheet.cell(row, 3).value
        if not code:
            continue
        item = items[item_id]
        raw_scores = (item.recognition_tags or {}).get('occasion_scores')
        if not isinstance(raw_scores, list) or len(raw_scores) != len(OCCASIONS):
            raise ValueError(f'{code}: incomplete saved model scores')
        scores = {}
        for entry in raw_scores:
            label, score = entry['occasion'], entry['score']
            if label not in OCCASIONS or label in scores or isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError(f'{code}: invalid model score')
            scores[label] = score
        selected = select_scored_occasions(scores, 0.8)
        cells[f'H{row}'] = ', '.join(selected)
        records.append({'code': code, 'item_id': item_id, 'occasion_scores': raw_scores,
                        'selected': selected, 'highest_score_fallback': max(scores.values()) < 0.8})
    write_cells(source, output, cells)
    report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'source_workbook': str(source.resolve()),
              'source_field': 'clothing_items.recognition_tags.occasion_scores',
              'threshold': 0.8, 'manual_overrides_applied': False,
              'fallback': 'One highest scoring occasion; ties follow taxonomy order',
              'garments': len(records), 'multi_occasion_items': sum(len(r['selected']) > 1 for r in records),
              'fallback_items': sum(r['highest_score_fallback'] for r in records),
              'verified': 'Only Garment Labels H2 and garment H cells changed; all other cell values and XLSX parts preserved',
              'items': records}
    output.with_suffix('.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'items'}, indent=2))
    print(f'Workbook: {output.resolve()}')


if __name__ == '__main__':
    main()
