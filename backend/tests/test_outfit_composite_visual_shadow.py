import base64
import io

from PIL import Image

from app.models.domain import ClothingItemRecord
from tools.evaluation.outfit_composite_visual_shadow import (
    _batch_schema,
    _chunks,
    _compose_outfit_image,
    _parse_batch,
    parser,
)


def _item(identifier, subtype):
    return ClothingItemRecord(
        id=identifier, user_id="user", image_url="", category="Tops",
        subtype=subtype, color="Blue",
    )


def test_eight_outfits_become_four_two_outfit_calls():
    batches = _chunks([f"O{index}" for index in range(8)])
    assert len(batches) == 4
    assert all(len(batch) == 2 for batch in batches)


def test_dynamic_schema_requires_exact_batch_size_and_ids():
    schema = _batch_schema(["S001-O01", "S001-O02"])
    reviews = schema["properties"]["reviews"]
    assert reviews["minItems"] == 2
    assert reviews["maxItems"] == 2
    assert schema["$defs"]["CompositeOutfitReview"]["properties"]["outfit_id"]["enum"] == [
        "S001-O01", "S001-O02",
    ]


def test_composite_contains_every_outfit_item_in_one_image():
    sources = [
        (_item("item-1", "T-shirt"), Image.new("RGB", (400, 600), "blue")),
        (_item("item-2", "Hoodie"), Image.new("RGB", (600, 400), "gray")),
        (_item("item-3", "Jacket"), Image.new("RGB", (500, 500), "black")),
    ]
    data_url, audit = _compose_outfit_image(sources, max_dimension=1024)
    assert data_url.startswith("data:image/jpeg;base64,")
    image = Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1])))
    assert max(image.size) <= 1024
    assert audit["tile_count"] == 3
    assert {row["item_id"] for row in audit["source_items"]} == {
        "item-1", "item-2", "item-3",
    }


def test_batch_parser_requires_supplied_order_and_coverage():
    criterion = '{"verdict":"pass","reason":"compatible"}'
    text = (
        '{"reviews":['
        '{"outfit_id":"O1","physical_fit":' + criterion
        + ',"style_silhouette":' + criterion
        + ',"color_pattern":' + criterion
        + ',"thermal_occasion":' + criterion + '},'
        '{"outfit_id":"O2","physical_fit":' + criterion
        + ',"style_silhouette":' + criterion
        + ',"color_pattern":' + criterion
        + ',"thermal_occasion":' + criterion + '}]}'
    )
    assert [review.outfit_id for review in _parse_batch(text, ["O1", "O2"]).reviews] == ["O1", "O2"]


def test_composite_cli_defaults_to_strict_schema():
    args = parser().parse_args([
        "run", "--suite-dir", "/tmp/suite", "--model", "model",
        "--base-url", "https://candidate.test/v1", "--protocol", "chat-completions",
        "--api-key-env", "KEY", "--input-rate", "0", "--cached-rate", "0",
        "--output-rate", "0",
    ])
    assert args.schema_mode == "json-schema"
