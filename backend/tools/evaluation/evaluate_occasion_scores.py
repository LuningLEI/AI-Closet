"""Evaluate the production occasion prompt on a reproducible sample, without DB writes."""
import argparse
import base64
import csv
from datetime import datetime, timezone
import html
import json
import mimetypes
from pathlib import Path
import random
import shutil
import time

from app.core.config import settings
from app.core.versions import TAXONOMY_PROMPT_VERSION
from app.services.recognition_service import ClothingRecognitionService
from app.services.taxonomy import OCCASIONS
from tools.evaluation.paths import PROJECT_ROOT, evaluation_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, default=PROJECT_ROOT / 'closet_picture')
    parser.add_argument('--count', type=int, default=10)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    photos = sorted(p for p in args.images.iterdir() if p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp'})
    if not settings.openai_api_key or not 0 < args.count <= len(photos):
        parser.error('Requires a configured API key and a valid image count')
    selected = random.Random(args.seed).sample(photos, args.count)
    out = evaluation_path('recognition', 'occasion_samples', datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    (out / 'images').mkdir(parents=True)
    report = dict(model=settings.openai_vision_model, detail=settings.openai_vision_detail,
                  prompt_version=TAXONOMY_PROMPT_VERSION, seed=args.seed, mode="all_scores_no_threshold", results=[])
    service = ClothingRecognitionService(occasion_threshold=0)
    for i, photo in enumerate(selected, 1):
        started = time.perf_counter()
        entry = dict(filename=photo.name, image=f'images/{photo.name}')
        shutil.copy2(photo, out / entry['image'])
        try:
            mime = mimetypes.guess_type(photo.name)[0] or 'image/jpeg'
            url = f'data:{mime};base64,' + base64.b64encode(photo.read_bytes()).decode()
            # Same production request and normalization, local bytes in place of signed URLs.
            # Direct vision call prevents heuristic fallbacks from counting as test successes.
            analysis = service._analyze_with_openai_vision(image_url=url)
            entry['analysis'] = analysis.model_dump(exclude={'occasion', 'occasion_threshold', 'raw_occasion'})
            entry['missing_labels'] = sorted(set(OCCASIONS) - {s.occasion for s in analysis.occasion_scores})
            entry['status'] = 'ok' if not entry['missing_labels'] else 'incomplete_scores'
        except Exception as error:
            entry.update(status='error', error_type=type(error).__name__)
        entry['latency_seconds'] = round(time.perf_counter() - started, 2)
        report['results'].append(entry)
        (out / 'results.json').write_text(json.dumps(report, indent=2))
        print(f"{i}/{len(selected)} {photo.name}: {entry['status']} ({entry['latency_seconds']}s)", flush=True)
        if entry['status'] == 'error':
            raise SystemExit(f"Stopped after {entry['error_type']}; partial results: {out}")
    with (out / 'scores.csv').open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['filename', 'occasion', 'score'])
        for entry in report['results']:
            for s in entry['analysis']['occasion_scores']:
                writer.writerow([entry['filename'], s['occasion'], s['score']])
    cards = []
    for e in report['results']:
        rows = ''.join(f'<tr><td>{html.escape(s["occasion"])}</td><td><meter min="0" max="1" value="{s["score"]}"></meter></td><td>{s["score"]:g}</td></tr>' for s in e['analysis']['occasion_scores'])
        cards.append(f'<article><h2>{html.escape(e["filename"])}</h2><img src="{html.escape(e["image"])}"><p>{html.escape(e["analysis"]["category"])} · {e["latency_seconds"]}s · {e["status"]}</p><table><tr><th>Occasion</th><th></th><th>Score</th></tr>{rows}</table></article>')
    page = '''<!doctype html><meta charset="utf-8"><title>Occasion scores · 10 photos</title>
<style>body{font:16px system-ui;margin:24px;background:#f5f5f5;color:#222}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px}article{background:white;padding:18px;border-radius:12px}img{width:100%;height:320px;object-fit:contain}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:6px;border-bottom:1px solid #eee}h2{font-size:18px}meter{width:100%}</style>
<h1>Occasion 适配系数 · 10 张图</h1><p>MODEL · DETAIL detail · seed SEED</p><p>显示全部场合的独立 0–1 适配分，按分数从高到低排列。未做 threshold 筛选。分数不要求总和为 1，也不是经过校准的概率。</p><main>CARDS</main>'''
    page = page.replace('MODEL', html.escape(report['model'])).replace('DETAIL', html.escape(report['detail'])).replace('SEED', str(args.seed)).replace('CARDS', ''.join(cards))
    (out / 'report.html').write_text(page)
    print(f'Report: {out / "report.html"}', flush=True)


if __name__ == '__main__':
    main()
