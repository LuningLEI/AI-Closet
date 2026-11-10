"""Export readable contact sheets for a frozen outfit visual-review suite."""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.services.storage_service import StorageService
from tools.evaluation.recognition_shadow import _resized_image_input, write_json_atomic


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def export(
    suite_dir: Path, output_dir: Path, rows_per_sheet: int = 5,
    verdict_run_dir: Path | None = None, passed_only: bool = False,
) -> list[Path]:
    manifest = json.loads((suite_dir / "suite_manifest.json").read_text())
    items = json.loads((suite_dir / "items.json").read_text())
    reviews_path = suite_dir / "reviews.json"
    if reviews_path.exists():
        reviews = json.loads(reviews_path.read_text())
    else:
        reviews = [
            {
                "review_id": row["outfit_id"],
                "source_scenario_id": row["scenario_id"],
                "source_model": row["source_model"],
                "item_ids": row["item_ids"],
            }
            for row in json.loads((suite_dir / "outfits.json").read_text())
        ]
    if passed_only:
        if verdict_run_dir is None:
            raise ValueError("passed_only requires a verdict_run_dir")
        verdicts = {
            row["outfit_id"]: row["model_verdict"]
            for row in json.loads((verdict_run_dir / "outfit_results.json").read_text())
        }
        reviews = [review for review in reviews if verdicts.get(review["review_id"]) == "pass"]
    preprocessing = manifest.get("image_preprocessing") or manifest.get("composite_preprocessing")
    max_dimension = int(preprocessing["max_dimension"])
    output_dir.mkdir(parents=True, exist_ok=True)
    assets = output_dir / "assets"
    assets.mkdir(exist_ok=True)
    storage = StorageService()
    client = httpx.Client(http2=False, timeout=90)
    audit_rows = []

    for review in reviews:
        image_paths = []
        image_audits = []
        for item_id in review["item_ids"]:
            item = items[item_id]
            signed_url = storage.signed_image_url(item["image_path"], expires_in=900)
            if not signed_url:
                raise RuntimeError(f"Unable to sign frozen image {item_id}")
            data_url, audit = _resized_image_input(
                signed_url, max_dimension=max_dimension, client=client, timeout=90,
            )
            encoded = data_url.split(",", 1)[1]
            image_path = assets / f"{review['review_id']}-{item_id}.jpg"
            image_path.write_bytes(base64.b64decode(encoded))
            image_paths.append(image_path)
            image_audits.append({"item_id": item_id, **audit})
        audit_rows.append({
            "review_id": review["review_id"],
            "item_ids": review["item_ids"],
            "images": [str(path.relative_to(output_dir)) for path in image_paths],
            "image_preprocessing": image_audits,
        })

    title_font = _font(26, bold=True)
    label_font = _font(20, bold=True)
    detail_font = _font(16)
    width = 1500
    row_height = 350
    header_height = 70
    thumbnail_size = (270, 250)
    outputs = []
    for page_start in range(0, len(reviews), rows_per_sheet):
        page_reviews = reviews[page_start:page_start + rows_per_sheet]
        canvas = Image.new("RGB", (width, header_height + row_height * len(page_reviews)), "white")
        draw = ImageDraw.Draw(canvas)
        page_number = page_start // rows_per_sheet + 1
        draw.rectangle((0, 0, width, header_height), fill="#1F4E78")
        draw.text(
            (28, 18), f"Outfit Visual Review Suite — Page {page_number}",
            font=title_font, fill="white",
        )
        for offset, review in enumerate(page_reviews):
            y = header_height + offset * row_height
            if offset % 2:
                draw.rectangle((0, y, width, y + row_height), fill="#F4F7FA")
            source = "GPT generator" if review["source_model"] == "gpt-4.1-mini" else "Qwen generator"
            draw.text(
                (24, y + 18),
                f"{review['review_id']} · {review['source_scenario_id']} · {source}",
                font=label_font, fill="#111111",
            )
            x = 24
            for item_id in review["item_ids"]:
                item = items[item_id]
                image_path = assets / f"{review['review_id']}-{item_id}.jpg"
                with Image.open(image_path) as opened:
                    image = ImageOps.fit(
                        opened.convert("RGB"), thumbnail_size, Image.Resampling.LANCZOS,
                    )
                    canvas.paste(image, (x, y + 60))
                subtype = item.get("subtype") or item.get("category") or "Unknown"
                color = item.get("color") or "Unknown"
                label = f"{subtype} · {color}"
                draw.text((x, y + 316), label[:32], font=detail_font, fill="#222222")
                x += 295
            draw.line((0, y + row_height - 1, width, y + row_height - 1), fill="#CCD5DD")
        output = output_dir / f"outfit-contact-sheet-{page_number}.jpg"
        canvas.save(output, "JPEG", quality=92)
        outputs.append(output)

    write_json_atomic(output_dir / "preview_index.json", {
        "suite_id": manifest["suite_id"],
        "contact_sheets": [path.name for path in outputs],
        "reviews": audit_rows,
    })
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rows-per-sheet", type=int, default=5)
    parser.add_argument("--verdict-run-dir", type=Path)
    parser.add_argument("--passed-only", action="store_true")
    args = parser.parse_args()
    outputs = export(
        args.suite_dir.resolve(), args.output_dir.resolve(), args.rows_per_sheet,
        args.verdict_run_dir.resolve() if args.verdict_run_dir else None,
        args.passed_only,
    )
    print(json.dumps([str(path) for path in outputs], indent=2))


if __name__ == "__main__":
    main()
