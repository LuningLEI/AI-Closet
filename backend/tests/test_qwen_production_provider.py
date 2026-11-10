import json
from pathlib import Path

from PIL import Image

from app.ai.gateway import AIResult
from app.models.domain import ClothingItemRecord
from app.outfits.config import load_config
from app.outfits.provider import VisionOutfitProvider


class LocalStorage:
    def signed_image_url(self, *_args, **_kwargs):
        return None


class Gateway:
    def __init__(self):
        self.calls = []

    def response(self, **kwargs):
        self.calls.append(kwargs)
        properties = kwargs["schema"]["properties"]
        if "selections" in properties:
            payload = {"selections": [{
                "candidate_index": 1, "selected_shoe_id": "shoe",
                "accessory_ids": ["bag"], "reason": "coherent",
            }]}
        else:
            criterion = {"verdict": "pass", "reason": "works"}
            checks = {name: criterion for name in ["wearability", "thermal", "color_pattern", "occasion"]}
            payload = {"reviews": [{
                "candidate_index": 1,
                "review": {"core": checks, "full": checks, "optional_layering": {
                    "verdict": "clear_improvement", "reason": "bag balances color",
                }},
                "optional_item_reviews": [{
                    "item_id": "bag", "verdict": "clear_improvement", "reason": "balances color",
                }],
            }]}
        return AIResult({"output_text": json.dumps(payload), "usage": {}})


def item(identifier, category, subtype, image_path):
    return ClothingItemRecord(
        id=identifier, user_id="00000000-0000-4000-8000-000000000123",
        image_url="", image_path=str(image_path), category=category, subtype=subtype,
        color="Black", season="Spring, Fall", style="Casual", occasion="Everyday",
        recognition_status="complete",
    )


def test_qwen_provider_sends_one_composite_per_outfit_and_strict_dynamic_schema(tmp_path: Path):
    image_path = tmp_path / "item.jpg"
    Image.new("RGB", (80, 120), "gray").save(image_path)
    top = item("top", "Tops", "T-shirt", image_path)
    bottom = item("bottom", "Bottoms", "Jeans", image_path)
    shoe = item("shoe", "Shoes", "Sneakers", image_path)
    bag = item("bag", "Bags", "Tote", image_path)
    gateway = Gateway()
    config = load_config().model_copy(update={
        "composite_visual_inputs": True, "per_optional_item_review": True,
        "evaluation_model": "qwen-vl", "footwear_selection_model": "qwen-vl",
    })
    provider = VisionOutfitProvider(config, storage=LocalStorage(), gateway=gateway)

    selection, _ = provider.select_accessories_batch([(1, [top, bottom], [shoe], [bag])])
    assert selection.selections[0].selected_shoe_id == "shoe"
    selection_images = [block for message in gateway.calls[0]["input"]
                        for block in (message["content"] if isinstance(message["content"], list) else [])
                        if block.get("type") == "input_image"]
    assert len(selection_images) == 1
    assert selection_images[0]["image_url"].startswith("data:image/jpeg;base64,")
    assert gateway.calls[0]["schema"]["properties"]["selections"]["maxItems"] == 1

    reviews, _ = provider.evaluate_batch([(1, [top, bottom, shoe, bag])])
    assert reviews.reviews[0].optional_item_reviews[0].item_id == "bag"
    review_images = [block for message in gateway.calls[1]["input"]
                     for block in (message["content"] if isinstance(message["content"], list) else [])
                     if block.get("type") == "input_image"]
    assert len(review_images) == 1
    assert gateway.calls[1]["schema"]["$defs"]["OptionalItemDecision"]["properties"]["item_id"] == {
        "type": "string", "enum": ["bag"],
    }
