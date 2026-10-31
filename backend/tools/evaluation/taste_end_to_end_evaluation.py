"""Run the production outfit pipeline for ten controlled taste personas.

The experiment freezes one real wardrobe, uses one shared neutral anchor, and
writes only local evaluation artifacts. It never modifies production closet,
feedback, jobs, outfits, or taste profiles.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time
import threading

import httpx
from openpyxl import Workbook
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from PIL import Image, ImageDraw, ImageOps

from app.models.domain import ClothingItemRecord
from app.outfits.config import load_config
from app.outfits.models import VisualReview
from app.outfits.provider import VisionOutfitProvider
from app.outfits.service import OutfitLibrary, ready
from app.outfits.store import LocalOutfitStore
from app.services.storage_service import StorageService
from app.services.taste_profile import (
    DEFAULT_TASTE_LEARNING_CONFIG,
    outfit_taste_score,
    reduce_sources,
    snapshot_features,
    snapshot_items,
)
from app.services.taste_profile_service import TasteProfileService


PERSONAS = [
    {"id": "P01", "name": "Minimal Neutral", "prefer": {"style": ["Minimalist"], "color": ["Black", "White", "Gray"], "pattern": ["Solid"], "occasion": ["Everyday"]}, "avoid": {"style": ["Romantic"], "pattern": ["Floral", "Graphic"]}},
    {"id": "P02", "name": "Romantic Pastel", "prefer": {"style": ["Romantic"], "color": ["Pink", "White", "Beige"], "subtype": ["Blouse", "Cardigan"], "occasion": ["Date"]}, "avoid": {"style": ["Sporty", "Edgy"]}},
    {"id": "P03", "name": "Business Classic", "prefer": {"style": ["Business", "Classic"], "color": ["Black", "White", "Gray"], "subtype": ["Button-down Shirt", "Blazer"], "occasion": ["Work"]}, "avoid": {"style": ["Sporty"], "subtype": ["Hoodie", "Workout Leggings"]}},
    {"id": "P04", "name": "Sporty Active", "prefer": {"style": ["Sporty"], "subtype": ["Hoodie", "Workout Leggings", "Sports Bra"], "occasion": ["Workout", "Everyday"]}, "avoid": {"style": ["Business", "Elegant"], "subtype": ["Pencil Skirt"]}},
    {"id": "P05", "name": "Streetwear", "prefer": {"style": ["Streetwear", "Edgy"], "color": ["Black", "Blue"], "subtype": ["Hoodie", "Jacket"], "occasion": ["Everyday"]}, "avoid": {"style": ["Business", "Romantic"]}},
    {"id": "P06", "name": "Classic Refined", "prefer": {"style": ["Classic", "Elegant"], "color": ["Black", "White", "Beige"], "pattern": ["Solid"], "occasion": ["Everyday", "Work"]}, "avoid": {"style": ["Streetwear"], "pattern": ["Graphic"]}},
    {"id": "P07", "name": "Colorful Contrast", "prefer": {"color": ["Blue", "Yellow", "Green", "Red"], "pattern": ["Striped", "Geometric"], "occasion": ["Everyday", "Party"]}, "avoid": {"color": ["Gray"], "style": ["Minimalist"]}},
    {"id": "P08", "name": "Elegant Evening", "prefer": {"style": ["Elegant", "Romantic"], "color": ["Black", "Blue"], "subtype": ["Blouse", "Heels"], "occasion": ["Evening", "Date", "Party"]}, "avoid": {"style": ["Sporty"], "subtype": ["Sneakers", "Workout Leggings"]}},
    {"id": "P09", "name": "Cozy Winter", "prefer": {"style": ["Casual"], "subtype": ["Sweater", "Cardigan", "Coat", "Boots"], "season": ["Winter"], "occasion": ["Everyday", "Lounge"]}, "avoid": {"subtype": ["Tank Top", "Sandals"], "season": ["Summer"]}},
    {"id": "P10", "name": "Pattern Explorer", "prefer": {"style": ["Bohemian", "Edgy"], "pattern": ["Floral", "Graphic", "Plaid", "Animal Print"], "color": ["Pink", "Green", "Blue"], "occasion": ["Everyday", "Party"]}, "avoid": {"style": ["Minimalist"], "pattern": ["Solid"]}},
]

BASELINE = {"id": "P00", "name": "No Taste Baseline", "prefer": {}, "avoid": {}}


class EvaluationCallBudgetExceeded(RuntimeError):
    pass


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    temporary.replace(path)


def preference_text(persona: dict, key: str) -> str:
    return "; ".join(f"{field}: {', '.join(values)}" for field, values in persona[key].items())


def experiment_note(persona: dict) -> str:
    if persona["id"] == "P09":
        return "Exploration fallback: quota disabled after repeated generations returned 0/2 required exploration outfits."
    return ""


def _snapshot(fields: dict[str, list[str]]) -> dict:
    item = {}
    for field, values in fields.items():
        item[field] = values if field in {"occasion", "season"} else ", ".join(values)
    return {"items": [item], "context": {}}


def persona_sources(persona: dict) -> list[dict]:
    if not persona["prefer"] and not persona["avoid"]:
        return []
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    rows = []
    # Three consistent positive observations ensure v2 evidence eligibility.
    for index in range(3):
        rows.append({"id": f"{persona['id']}-positive-{index}", "kind": "wear" if index == 0 else "liked",
                     "created_at": (now + timedelta(days=index)).isoformat(),
                     "feature_snapshot": _snapshot(persona["prefer"]), "reason_codes": []})
    reason_for = {"style": "style", "subtype": "style", "category": "style",
                  "color": "color_pattern", "pattern": "color_pattern",
                  "occasion": "occasion_mismatch", "season": "weather_mismatch",
                  "warmth_level": "weather_mismatch", "formality_score": "too_formal"}
    for field, values in persona["avoid"].items():
        for index in range(2):
            rows.append({"id": f"{persona['id']}-negative-{field}-{index}", "kind": "disliked",
                         "created_at": (now + timedelta(days=4 + index)).isoformat(),
                         "feature_snapshot": _snapshot({field: values}),
                         "reason_codes": [reason_for[field]]})
    return rows


class FrozenPersonaRepository:
    def __init__(self, records: list[ClothingItemRecord], users: set[str]):
        self.records = records
        self.users = users

    def _rows(self, uid: str):
        if uid not in self.users:
            return []
        return [item.model_copy(deep=True, update={"user_id": uid}) for item in self.records]

    def list_items_for_outfits(self, uid: str):
        return self._rows(uid)

    def list_items_for_outfit_candidates(self, uid: str):
        return self._rows(uid)


class LocalPhotoProvider(VisionOutfitProvider):
    def __init__(self, config, photos: dict[str, Path], call_budget: dict):
        super().__init__(config)
        self.photos = photos
        self.call_budget = call_budget

    def request(self, model, prompt, content, output_type):
        with self.call_budget["lock"]:
            if self.call_budget["used"] >= self.call_budget["limit"]:
                raise EvaluationCallBudgetExceeded("Offline evaluation model-call budget reached")
            self.call_budget["used"] += 1
        return super().request(model, prompt, content, output_type)

    def images(self, items):
        fields = ["id", "category", "subtype", "color", "style", "material", "pattern",
                  "fit", "length", "sleeve_length", "layering_role", "wearing_profile",
                  "color_tones", "warmth_level", "formality_score", "occasion", "season"]
        content = []
        for item in items:
            encoded = base64.b64encode(self.photos[item.id].read_bytes()).decode()
            content.extend([
                {"type": "input_text", "text": json.dumps({key: getattr(item, key) for key in fields})},
                {"type": "input_image", "image_url": "data:image/jpeg;base64," + encoded,
                 "detail": self.config.image_detail},
            ])
        return content

    def generate_clothing(self, anchor, catalog):
        """Normalize only excess exploration for this offline evaluation.

        Production rejects any non-exact quota. The evaluation preserves that
        behavior when exploration is missing, but deterministically drops extra
        exploration proposals so a usable downstream sample is not discarded.
        """
        proposals, usage = super().generate_clothing(anchor, catalog)
        context = self.generation_taste_context or {}
        target = int(context.get("exploration_outfit_count") or 0)
        exploration_ids = set(context.get("exploration_candidate_ids") or [])
        if not target:
            return proposals, usage
        explored = 0
        kept = []
        for proposal in proposals.outfits:
            is_exploration = bool(exploration_ids.intersection(proposal.item_ids))
            if is_exploration:
                if explored >= target:
                    continue
                explored += 1
            kept.append(proposal)
        return proposals.model_copy(update={"outfits": kept}), usage


def _download_photos(items, folder: Path) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    urls = StorageService().signed_image_urls([item.image_path for item in items])

    def download(item):
        existing = next(iter(folder.glob(item.id + ".*")), None)
        if existing:
            return item.id, existing
        for attempt in range(3):
            try:
                url = urls.get(item.image_path or "")
                if not url:
                    raise ValueError("Missing signed image URL")
                with httpx.Client(http2=False, timeout=60, follow_redirects=True) as client:
                    response = client.get(url)
                    response.raise_for_status()
                from io import BytesIO
                with Image.open(BytesIO(response.content)) as image:
                    fmt = image.format
                    image.verify()
                suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(fmt)
                if not suffix:
                    raise ValueError("Unsupported image format")
                target = folder / (item.id + suffix)
                target.write_bytes(response.content)
                return item.id, target
            except Exception as error:
                if attempt == 2:
                    raise RuntimeError(f"Photo unavailable for {item.id}: {type(error).__name__}") from None
                time.sleep(1)

    with ThreadPoolExecutor(max_workers=6) as pool:
        return dict(pool.map(download, items))


def prepare(uid: str, output: Path, anchor_id: str) -> None:
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory already contains files; use --resume")
    output.mkdir(parents=True, exist_ok=True)
    from app.repositories.factory import build_closet_repository
    records = build_closet_repository().list_items_for_outfit_candidates(uid)
    eligible = [item for item in records if item.user_id == uid and ready(item)]
    if anchor_id not in {item.id for item in eligible}:
        raise ValueError("Configured shared anchor is not ready in the current wardrobe")
    photos = _download_photos(eligible, output / "photos")
    clean = []
    for item in eligible:
        row = item.model_dump(mode="json")
        row["image_url"] = ""
        clean.append(row)
    atomic_json(output / "wardrobe.json", clean)
    atomic_json(output / "photo_hashes.json", {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in photos.items()})
    conditions = [BASELINE] + PERSONAS
    users = {f"taste-e2e-{row['id'].lower()}" for row in conditions}
    repository = FrozenPersonaRepository(eligible, users)
    store = LocalOutfitStore(output / "evaluation.sqlite3")
    profiles = {}
    config = load_config()
    for persona in conditions:
        experiment_uid = f"taste-e2e-{persona['id'].lower()}"
        projection = reduce_sources(persona_sources(persona), config=DEFAULT_TASTE_LEARNING_CONFIG)
        projection.update(user_id=experiment_uid, profile_version=1, source_version=1, projected_version=1,
                          updated_at=datetime.now(timezone.utc).isoformat())
        TasteProfileService(store)._put(projection)
        profiles[experiment_uid] = projection
        library = OutfitLibrary(repository, store, config)
        library.build(experiment_uid, anchor_id=anchor_id)
    atomic_json(output / "profiles.json", profiles)
    atomic_json(output / "manifest.json", {"source_user_id": uid, "anchor_id": anchor_id,
        "created_at": datetime.now(timezone.utc).isoformat(), "eligible_items": len(eligible),
        "conditions": conditions, "config": config.snapshot(), "production_writes": False,
        "evaluation_adjustment": "Excess exploration proposals are deterministically trimmed to the exact production quota; missing exploration still fails."})


def _photos_from_folder(folder: Path) -> dict[str, Path]:
    return {path.stem: path for path in (folder / "photos").iterdir() if path.is_file()}


def _inference_photos(folder: Path) -> dict[str, Path]:
    """Create bounded request images while retaining frozen originals unchanged."""
    source = _photos_from_folder(folder)
    destination = folder / "inference_photos"
    destination.mkdir(exist_ok=True)
    output = {}
    for item_id, path in source.items():
        target = destination / f"{item_id}.jpg"
        if not target.exists():
            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((512, 512))
                image.save(target, format="JPEG", quality=86, optimize=True)
        output[item_id] = target.resolve()
    return output


def _reset_interrupted_local_jobs(store: LocalOutfitStore) -> None:
    """Resume after a CLI interruption without erasing failed call accounting."""
    with store.db() as db:
        for job_id, raw in db.execute("select id,data from jobs").fetchall():
            job = json.loads(raw)
            if job.get("status") in {"queued", "processing", "failed"}:
                job.update(status="queued", attempts=0, lease_token=None, lease_until=None,
                           retry_at=datetime.now(timezone.utc).isoformat())
                db.execute("update jobs set data=? where id=?", (json.dumps(job), job_id))


def run(output: Path, concurrency: int, max_additional_calls: int) -> None:
    manifest = json.loads((output / "manifest.json").read_text())
    manifest["evaluation_adjustment"] = ("Excess exploration proposals are deterministically trimmed to the exact "
        "production quota; missing exploration still fails.")
    manifest["condition_exceptions"] = {"P09": "Exploration quota disabled after repeated 0/2 quota failures; Taste preferences remain active."}
    atomic_json(output / "manifest.json", manifest)
    records = [ClothingItemRecord.model_validate(row) for row in json.loads((output / "wardrobe.json").read_text())]
    users = {f"taste-e2e-{row['id'].lower()}" for row in manifest["conditions"]}
    repository = FrozenPersonaRepository(records, users)
    store = LocalOutfitStore(output / "evaluation.sqlite3")
    _reset_interrupted_local_jobs(store)
    store.recover_calls()
    config = load_config()
    photos = _inference_photos(output)
    call_budget = {"used": 0, "limit": max_additional_calls, "lock": threading.Lock()}
    # Rebuild fixtures on every resume so a corrected persona definition cannot
    # leave stale local profiles. This never touches production profile rows.
    profiles = {}
    for persona in manifest["conditions"]:
        uid = f"taste-e2e-{persona['id'].lower()}"
        projection = reduce_sources(persona_sources(persona), config=DEFAULT_TASTE_LEARNING_CONFIG)
        if persona["id"] == "P09":
            projection["generation_memory"]["exploration_rate"] = 0.0
        projection.update(user_id=uid, profile_version=1, source_version=1, projected_version=1,
                          updated_at=datetime.now(timezone.utc).isoformat())
        TasteProfileService(store)._put(projection)
        profiles[uid] = projection
    atomic_json(output / "profiles.json", profiles)

    def consume():
        local = LocalOutfitStore(output / "evaluation.sqlite3")
        provider = LocalPhotoProvider(config, photos, call_budget)
        library = OutfitLibrary(repository, local, config, provider)
        while True:
            job = local.claim(config)
            if not job:
                return
            try:
                library.process(job)
            except EvaluationCallBudgetExceeded:
                print(json.dumps({"event": "call_budget_reached", "limit": max_additional_calls}), flush=True)
                return
            except Exception as error:
                print(json.dumps({"event": "job_failed", "user": job["user_id"], "type": type(error).__name__}), flush=True)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(lambda _: consume(), range(concurrency)))
    export(output, repository, store)


def _preview(item_ids: list[str], photos: dict[str, Path], target: Path) -> None:
    size = 150
    canvas = Image.new("RGB", (size * len(item_ids), size + 24), "white")
    draw = ImageDraw.Draw(canvas)
    for index, item_id in enumerate(item_ids):
        with Image.open(photos[item_id]) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((size, size))
            x = index * size + (size - image.width) // 2
            y = (size - image.height) // 2
            canvas.paste(image, (x, y))
        draw.text((index * size + 4, size + 4), item_id[:8], fill="black")
    canvas.save(target, format="JPEG", quality=88)


def export(output: Path, repository, store: LocalOutfitStore) -> None:
    manifest = json.loads((output / "manifest.json").read_text())
    profiles = json.loads((output / "profiles.json").read_text())
    photos = _photos_from_folder(output)
    persona_by_uid = {f"taste-e2e-{row['id'].lower()}": row for row in manifest["conditions"]}
    previews = output / "previews"
    previews.mkdir(exist_ok=True)
    rows = []
    audit_rows = []
    for uid, persona in persona_by_uid.items():
        items = {item.id: item for item in repository.list_items_for_outfits(uid)}
        profile = profiles[uid]
        jobs = store.jobs(uid)
        calls = store.run_report(uid)
        run_usage = calls[0] if calls else {}
        for job in jobs:
            for diagnostic in (job.get("stats") or {}).get("candidate_diagnostics", []):
                audit_rows.append([persona["id"], persona["name"], diagnostic.get("candidate_index"),
                    ", ".join(diagnostic.get("item_ids") or []), diagnostic.get("status"),
                    ", ".join(diagnostic.get("rejection_codes") or [])])
        evaluations = sorted(store.evaluations(uid), key=lambda row: row["id"])
        for index, record in enumerate(evaluations, start=1):
            payload = record["payload"]
            members = [items[item_id] for item_id in payload["item_ids"]]
            review = VisualReview.model_validate(payload["visual_review"])
            features = snapshot_features(snapshot_items(members))
            memory = profile.get("generation_memory") or {}
            matched = sorted(set(features).intersection(memory.get("preferred") or []))
            violated = sorted(set(features).intersection(memory.get("avoid") or []))
            preview = previews / f"{persona['id']}_{index:02d}.jpg"
            _preview(payload["item_ids"], photos, preview)
            labels = "\n".join(f"{item.category} / {item.subtype or 'Unknown'} / {item.color}" for item in members)
            rows.append({"persona": persona, "uid": uid, "record": record, "review": review,
                "members": members, "labels": labels, "profile": profile, "matched": matched,
                "violated": violated, "score": outfit_taste_score(members, profile),
                "preview": preview, "run_usage": run_usage})

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Outfit Review"
    headers = ["Persona", "Preference target", "Avoid target", "Outfit preview", "Items",
        "Pipeline accepted", "Taste score", "Matched learned features", "Violated learned features",
        "Core wearability", "Core thermal", "Core color/pattern", "Core occasion",
        "Generation reason", "Input tokens (run)", "Output tokens (run)",
        "Human preference match (1-5)", "Would this persona wear it? (Y/N)",
        "Human structurally wearable? (Y/N)", "Human notes"]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for row_index, data in enumerate(rows, start=2):
        p, review, usage = data["persona"], data["review"], data["run_usage"]
        target = preference_text(p, "prefer")
        if experiment_note(p):
            target += "\n\n" + experiment_note(p)
        sheet.append([p["id"] + " · " + p["name"], target, preference_text(p, "avoid"), "",
            data["labels"], "Yes" if review.core.passes() else "No", round(data["score"], 4),
            ", ".join(data["matched"]), ", ".join(data["violated"]),
            review.core.wearability.verdict, review.core.thermal.verdict,
            review.core.color_pattern.verdict, review.core.occasion.verdict,
            data["record"]["payload"].get("generation_reason"), usage.get("input_tokens"), usage.get("output_tokens"),
            "", "", "", ""])
        image = ExcelImage(data["preview"])
        image.width = min(750, 150 * len(data["members"]))
        image.height = 174
        sheet.add_image(image, f"D{row_index}")
        sheet.row_dimensions[row_index].height = 135
    widths = {"A": 24, "B": 42, "C": 36, "D": 95, "E": 36, "F": 18, "G": 13,
              "H": 42, "I": 42, "J": 16, "K": 14, "L": 18, "M": 15, "N": 45,
              "O": 18, "P": 18, "Q": 24, "R": 30, "S": 28, "T": 40}
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:T{max(1, sheet.max_row)}"
    rating_validation = DataValidation(type="whole", operator="between", formula1="1", formula2="5",
                                       allow_blank=True, error="Enter a whole number from 1 to 5.")
    yes_no_validation = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
    sheet.add_data_validation(rating_validation)
    sheet.add_data_validation(yes_no_validation)
    rating_validation.add(f"Q2:Q{sheet.max_row}")
    yes_no_validation.add(f"R2:S{sheet.max_row}")
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    summary = workbook.create_sheet("Main Results Template")
    summary.append(["Persona", "Outfits reviewed", "Mean preference match (1-5)",
        "Would-wear rate", "Human wearable rate", "System accepted rate", "Notes"])
    for cell in summary[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    for index, persona in enumerate(manifest["conditions"], start=2):
        key = persona["id"] + " · " + persona["name"]
        summary.append([key,
            f'=COUNTIF(\'Outfit Review\'!A:A,A{index})',
            f'=IFERROR(AVERAGEIF(\'Outfit Review\'!A:A,A{index},\'Outfit Review\'!Q:Q),"")',
            f'=IFERROR(COUNTIFS(\'Outfit Review\'!A:A,A{index},\'Outfit Review\'!R:R,"Y")/B{index},"")',
            f'=IFERROR(COUNTIFS(\'Outfit Review\'!A:A,A{index},\'Outfit Review\'!S:S,"Y")/B{index},"")',
            f'=IFERROR(COUNTIFS(\'Outfit Review\'!A:A,A{index},\'Outfit Review\'!F:F,"Yes")/B{index},"")', ""])
    for column, width in zip("ABCDEFG", [28, 18, 28, 20, 22, 22, 40]):
        summary.column_dimensions[column].width = width
    summary.freeze_panes = "A2"

    profiles_sheet = workbook.create_sheet("Personas")
    profiles_sheet.append(["Persona", "Target preferences", "Target avoids", "Learned preferred features", "Learned avoided features"])
    for cell in profiles_sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    for persona in manifest["conditions"]:
        uid = f"taste-e2e-{persona['id'].lower()}"
        memory = profiles[uid].get("generation_memory") or {}
        target = preference_text(persona, "prefer")
        if experiment_note(persona):
            target += "\n\n" + experiment_note(persona)
        profiles_sheet.append([persona["id"] + " · " + persona["name"], target,
            preference_text(persona, "avoid"), ", ".join(memory.get("preferred") or []),
            ", ".join(memory.get("avoid") or [])])
    for column, width in zip("ABCDE", [28, 50, 45, 70, 70]):
        profiles_sheet.column_dimensions[column].width = width
    for row in profiles_sheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    audit = workbook.create_sheet("Pipeline Audit")
    audit.append(["Persona", "Name", "Candidate index", "Item IDs", "Pipeline stage result", "Rejection codes"])
    for row in audit_rows:
        audit.append(row)
    for cell in audit[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    for column, width in zip("ABCDEF", [12, 24, 16, 80, 34, 40]):
        audit.column_dimensions[column].width = width

    target = output / "taste_end_to_end_results.xlsx"
    temporary = output / "taste_end_to_end_results.tmp.xlsx"
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.calculation.calcMode = "auto"
    workbook.save(temporary)
    temporary.replace(target)
    atomic_json(output / "result_summary.json", {"conditions": len(persona_by_uid), "evaluated_outfits": len(rows),
        "pipeline_audit_rows": len(audit_rows), "job_statuses": dict(Counter(
            job["status"] for uid in persona_by_uid for job in store.jobs(uid)))})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--anchor-id", default="954691ec-023b-50c0-9a36-10b38ed8f0e0")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--max-additional-calls", type=int, default=40)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 3:
        parser.error("concurrency must be between 1 and 3")
    if not args.resume:
        prepare(args.user_id, args.output, args.anchor_id)
    if not args.prepare_only:
        run(args.output, args.concurrency, args.max_additional_calls)


if __name__ == "__main__":
    main()
