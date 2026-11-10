from app.models.domain import ClothingItemRecord
from app.outfits.config import load_config
from app.outfits.models import CurrentVisualReview, OptionalLayerReview, VisualChecks, VisualCriterion
from tools.evaluation.outfit_full_pipeline_shadow import (
    IMAGES_PER_CALL,
    OptionalItemDecision,
    _chunks,
    _normalize_snapshot_row,
    _project,
    _review_schema,
    _selection_context,
    _selection_schema,
    _shadow_accessories_for,
    _shadow_clothing_codes,
)


def item(item_id: str, category: str, subtype: str) -> ClothingItemRecord:
    return ClothingItemRecord(
        id=item_id,
        user_id="user-1",
        image_url="https://example.invalid/item.jpg",
        image_path=f"user-1/{item_id}.jpg",
        category=category,
        subtype=subtype,
        color="Black",
        season="Spring, Fall",
        style="Casual",
        occasion="Everyday",
    )


def checks() -> VisualChecks:
    criterion = lambda: VisualCriterion(verdict="pass", reason="The supplied garments are coherent.")
    return VisualChecks(
        wearability=criterion(), thermal=criterion(),
        color_pattern=criterion(), occasion=criterion(),
    )


def review(optional: str) -> CurrentVisualReview:
    return CurrentVisualReview(
        core=checks(), full=checks(),
        optional_layering=OptionalLayerReview(
            verdict=optional, reason="Compared with the independently wearable base.",
        ),
    )


def test_every_model_batch_contains_at_most_two_images():
    assert IMAGES_PER_CALL == 2
    assert _chunks(list(range(7))) == [[0, 1], [2, 3], [4, 5], [6]]


def test_dynamic_schemas_require_exact_ordered_batch_size():
    selection = _selection_schema(["S001-C01", "S001-C02"])
    review_schema = _review_schema(["S001-C01"], ["bag", "scarf"])
    assert selection["properties"]["selections"]["minItems"] == 2
    assert selection["properties"]["selections"]["maxItems"] == 2
    assert selection["$defs"]["AccessorySelection"]["properties"]["candidate_id"]["enum"] == [
        "S001-C01", "S001-C02",
    ]
    assert review_schema["properties"]["reviews"]["minItems"] == 1
    assert review_schema["properties"]["reviews"]["maxItems"] == 1
    assert review_schema["$defs"]["OptionalItemDecision"]["properties"]["item_id"]["enum"] == [
        "bag", "scarf",
    ]


def test_snapshot_vectors_are_normalized_without_mutating_source():
    source = {"semantic_vector": "[0.1, 0.2]", "feature_vector": "not-json"}
    normalized = _normalize_snapshot_row(source)
    assert source["semantic_vector"] == "[0.1, 0.2]"
    assert normalized["semantic_vector"] == [0.1, 0.2]
    assert normalized["feature_vector"] is None


def test_accessory_selection_receives_metadata_for_every_visual_candidate():
    items = {
        value.id: value for value in [
            item("top", "Tops", "T-shirt"),
            item("shoe", "Shoes", "Sneakers"),
            item("bag", "Bags", "Crossbody Bag"),
        ]
    }
    context = _selection_context({
        "candidate_id": "S001-C01", "scenario_id": "S001", "anchor_item_id": "top",
        "clothing_item_ids": ["top"], "candidate_shoe_ids": ["shoe"],
        "candidate_accessory_ids": ["bag"], "maximum_accessories": 1,
        "generation_reason": "frozen",
    }, items)
    assert context["clothing_items"][0]["subtype"] == "T-shirt"
    assert context["shoe_candidates"][0]["category"] == "Shoes"
    assert context["accessory_candidates"][0]["category"] == "Bags"


def test_no_improvement_removes_bag_but_keeps_valid_core():
    members = [
        item("top", "Tops", "T-shirt"),
        item("bottom", "Bottoms", "Jeans"),
        item("shoe", "Shoes", "Sneakers"),
        item("bag", "Bags", "Crossbody Bag"),
    ]
    projection = _project(members, review("no_improvement"), load_config())
    assert projection["admitted"] is True
    assert projection["core_item_ids"] == ["top", "bottom", "shoe"]
    assert projection["optional_item_ids"] == []
    assert projection["removed_optional_item_ids"] == ["bag"]


def test_clear_improvement_keeps_optional_bag():
    members = [
        item("top", "Tops", "T-shirt"),
        item("bottom", "Bottoms", "Jeans"),
        item("shoe", "Shoes", "Sneakers"),
        item("bag", "Bags", "Crossbody Bag"),
    ]
    projection = _project(members, review("clear_improvement"), load_config())
    assert projection["admitted"] is True
    assert projection["optional_item_ids"] == ["bag"]


def test_ski_pants_require_a_warm_upper_layer_in_shadow_policy():
    ski = item("ski", "Activewear", "Ski Pants").model_copy(update={"warmth_level": 4})
    bra = item("bra", "Activewear", "Sports Bra").model_copy(update={"warmth_level": 1})
    sweater = item("sweater", "Tops", "Sweater").model_copy(update={"warmth_level": 4})
    assert _shadow_clothing_codes([ski, bra]) == ["ski_pants_without_warm_upper_coverage"]
    assert _shadow_clothing_codes([ski, bra, sweater]) == []


def test_color_responsive_pool_preserves_pink_and_blue_scarves():
    config = load_config().model_copy(update={"vision_accessory_limit": 4})
    sweater = item("sweater", "Tops", "Sweater").model_copy(update={"color": "Beige, Blue"})
    pants = item("pants", "Bottoms", "Wide-leg Pants").model_copy(update={"color": "Pink"})
    accessories = [
        item("black", "Accessories", "Scarf").model_copy(update={"color": "Black"}),
        item("blue", "Accessories", "Scarf").model_copy(update={"color": "Blue, Beige"}),
        item("pink", "Accessories", "Scarf").model_copy(update={"color": "Pink"}),
        item("blue-hat", "Accessories", "Hat").model_copy(update={"color": "Blue, White"}),
        item("multicolor-bag", "Bags", "Crossbody Bag").model_copy(
            update={"color": "Blue, Pink, Black, White"},
        ),
        item("bag", "Bags", "Tote").model_copy(update={"color": "Beige"}),
        item("hat", "Accessories", "Hat").model_copy(update={"color": "Black, Beige"}),
    ]
    selected = _shadow_accessories_for([sweater, pants], pants, accessories, config)
    assert {value.id for value in selected} >= {"blue", "pink"}
    assert len(selected) == 4


def test_per_item_review_drops_weak_scarf_but_keeps_clear_bag():
    members = [
        item("top", "Tops", "T-shirt"),
        item("bottom", "Bottoms", "Jeans"),
        item("shoe", "Shoes", "Sneakers"),
        item("bag", "Bags", "Crossbody Bag"),
        item("scarf", "Accessories", "Scarf"),
    ]
    decisions = [
        OptionalItemDecision(item_id="bag", verdict="clear_improvement", reason="Balances the outfit."),
        OptionalItemDecision(item_id="scarf", verdict="no_improvement", reason="Adds no visible benefit."),
    ]
    projection = _project(members, review("clear_improvement"), load_config(), decisions)
    assert projection["optional_item_ids"] == ["bag"]
    assert projection["removed_optional_item_ids"] == ["scarf"]
