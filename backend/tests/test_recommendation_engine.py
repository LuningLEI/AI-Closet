from __future__ import annotations

from app.models.domain import ClothingItemRecord, RecommendationContext
from app.services.recommendation import RecommendationEngine
from app.services.recommendation.candidates import CandidateGenerator


class StaticEmbeddingService:
    def create_embedding(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


def closet_item(
    item_id: str,
    category: str,
    subtype: str,
    color: str = "White",
    style: str = "Casual",
    occasion: str = "Everyday",
    season: str = "All-Season",
    summary: str = "",
) -> ClothingItemRecord:
    return ClothingItemRecord(
        id=item_id,
        user_id="00000000-0000-4000-8000-0000000000a1",
        image_url=f"https://example.test/{item_id}.jpg",
        image_path=f"user/{item_id}.jpg",
        category=category,
        subtype=subtype,
        color=color,
        season=season,
        style=style,
        occasion=occasion,
        recognition_source="OpenAI Vision",
        recognition_summary=summary,
        semantic_vector=[1.0, 0.0, 0.0],
    )


def test_recommendation_engine_keeps_a_single_top_and_optional_outerwear() -> None:
    engine = RecommendationEngine(embedding_service=StaticEmbeddingService())
    recommendations = engine.recommend(
        [
            closet_item("shirt", "Tops", "Button-down Shirt", summary="light shirt"),
            closet_item("coat", "Outerwear", "Wool Coat", summary="structured coat"),
            closet_item("jeans", "Bottoms", "Jeans", color="Blue"),
            closet_item("sneakers", "Shoes", "Sneakers"),
        ],
        RecommendationContext(occasion="Everyday", temperature_f=58, preferred_style="Casual", limit=5),
    )

    assert recommendations
    assert all(len([item for item in recommendation.items if item.category == "Tops"]) == 1 for recommendation in recommendations)
    assert any(any(item.category == "Outerwear" for item in recommendation.items) for recommendation in recommendations)
    assert recommendations[0].score >= recommendations[-1].score


def test_recommendation_engine_prefers_outfits_over_single_item_fallbacks() -> None:
    engine = RecommendationEngine(embedding_service=StaticEmbeddingService())
    recommendations = engine.recommend(
        [
            closet_item("tee", "Tops", "T-shirt", summary="cotton tee"),
            closet_item("trousers", "Bottoms", "Trousers", color="Black", style="Casual"),
            closet_item("loafers", "Shoes", "Loafers", color="Black", style="Casual"),
            closet_item("bag", "Bags", "Shoulder Bag", color="Black", style="Casual"),
        ],
        RecommendationContext(occasion="Everyday", temperature_f=72, preferred_style="Casual", limit=5),
    )

    assert recommendations
    assert all(len(recommendation.items) >= 3 for recommendation in recommendations)
    assert all(any(item.category == "Shoes" for item in recommendation.items) for recommendation in recommendations)


def test_recommendation_engine_prioritizes_unique_lead_items_before_reusing_them() -> None:
    engine = RecommendationEngine(embedding_service=StaticEmbeddingService())
    recommendations = engine.recommend(
        [
            closet_item("shirt-a", "Tops", "Button-down Shirt", color="Beige", style="Casual"),
            closet_item("shirt-b", "Tops", "Blouse", color="White", style="Formal"),
            closet_item("jeans", "Bottoms", "Jeans", color="Blue"),
            closet_item("skirt", "Bottoms", "Skirt", color="Black", style="Formal"),
            closet_item("sneakers", "Shoes", "Sneakers", color="White"),
            closet_item("heels", "Shoes", "Heels", color="Black", style="Formal"),
        ],
        RecommendationContext(occasion="Everyday", temperature_f=70, preferred_style="Casual", limit=5),
    )

    assert recommendations
    lead_ids = [
        (
            next((item for item in recommendation.items if item.category in {"Tops", "Dresses", "Jumpsuits", "Sets", "Swimwear"}), None)
            or recommendation.items[0]
        ).id
        for recommendation in recommendations
    ]

    assert lead_ids[:2] == ["shirt-a", "shirt-b"]


def test_recommendation_engine_respects_user_selected_categories() -> None:
    engine = RecommendationEngine(embedding_service=StaticEmbeddingService())
    recommendations = engine.recommend(
        [
            closet_item("dress", "Dresses", "Slip Dress", style="Elegant", occasion="Party"),
            closet_item("tank", "Tops", "Tank Top"),
        ],
        RecommendationContext(occasion="Party", temperature_f=76, preferred_style="Elegant", limit=5),
        {"taxonomy": {"selected_categories": ["Tops"], "custom_categories": []}},
    )

    assert recommendations
    assert all(item.category == "Tops" for recommendation in recommendations for item in recommendation.items)


def test_candidate_generator_shortlists_context_relevant_items_before_pairing() -> None:
    generator = CandidateGenerator()
    context = RecommendationContext(occasion="Work", temperature_f=84, preferred_style="Business", preferred_color="Blue", limit=5)
    grouped = generator.group_by_category(
        [
            closet_item("work-shirt-blue", "Tops", "Blouse", color="Blue", style="Business", occasion="Work", season="Summer"),
            closet_item("work-shirt-white", "Tops", "Button-down Shirt", color="White", style="Business", occasion="Work", season="Summer"),
            closet_item("party-top", "Tops", "Sequin Top", color="Pink", style="Elegant", occasion="Party", season="Winter"),
            closet_item("hoodie", "Tops", "Hoodie", color="Black", style="Casual", occasion="Everyday", season="Winter"),
            closet_item("jeans", "Bottoms", "Jeans", color="Blue", style="Casual", occasion="Everyday", season="All-Season"),
            closet_item("trousers", "Bottoms", "Trousers", color="Black", style="Business", occasion="Work", season="Summer"),
            closet_item("shorts", "Bottoms", "Shorts", color="Blue", style="Casual", occasion="Everyday", season="Summer"),
            closet_item("boots", "Shoes", "Boots", color="Black", style="Casual", occasion="Everyday", season="Winter"),
            closet_item("heels", "Shoes", "Heels", color="Blue", style="Business", occasion="Work", season="Summer"),
        ],
        context,
        {"profile": {"style_preferences": ["Business"]}},
    )

    assert [item.id for item in grouped["Tops"]] == [
        "work-shirt-blue",
        "work-shirt-white",
        "hoodie",
        "party-top",
    ]
    assert [item.id for item in grouped["Bottoms"]] == ["trousers", "jeans", "shorts"]
    assert [item.id for item in grouped["Shoes"]] == ["heels", "boots"]


def test_recommendation_engine_penalizes_heavy_outerwear_over_light_dress() -> None:
    engine = RecommendationEngine(embedding_service=StaticEmbeddingService())
    recommendations = engine.recommend(
        [
            closet_item("slip-dress", "Dresses", "Slip Dress", color="White", style="Elegant", occasion="Date", season="Summer", summary="light slip dress"),
            closet_item("puffer", "Outerwear", "Puffer Coat", color="Black", style="Casual", occasion="Everyday", season="Winter", summary="heavy puffer coat"),
            closet_item("cardigan", "Outerwear", "Cardigan", color="Beige", style="Elegant", occasion="Date", season="Spring", summary="light cardigan"),
            closet_item("heels", "Shoes", "Heels", color="Beige", style="Elegant", occasion="Date", season="Summer"),
        ],
        RecommendationContext(occasion="Date", temperature_f=68, preferred_style="Elegant", limit=5),
    )

    assert recommendations
    recommendation_ids = [[item.id for item in recommendation.items] for recommendation in recommendations]
    assert "puffer" not in recommendation_ids[0]
    puffer_rank = next(
        (index for index, ids in enumerate(recommendation_ids) if "puffer" in ids),
        None,
    )
    cardigan_rank = next(
        (index for index, ids in enumerate(recommendation_ids) if "cardigan" in ids),
        None,
    )
    assert puffer_rank is not None
    assert cardigan_rank is None or cardigan_rank < puffer_rank


def test_recommendation_engine_penalizes_competing_colors() -> None:
    engine = RecommendationEngine(embedding_service=StaticEmbeddingService())
    recommendations = engine.recommend(
        [
            closet_item("blue-shirt", "Tops", "Shirt", color="Blue", style="Casual"),
            closet_item("black-pants", "Bottoms", "Trousers", color="Black", style="Casual"),
            closet_item("white-shoes", "Shoes", "Sneakers", color="White", style="Casual"),
            closet_item("red-bag", "Bags", "Bag", color="Red", style="Casual"),
            closet_item("green-bag", "Bags", "Bag", color="Green", style="Casual"),
        ],
        RecommendationContext(occasion="Everyday", temperature_f=70, preferred_style="Casual", limit=5),
    )

    assert recommendations
    top_colors = {item.color for item in recommendations[0].items}
    assert not {"Red", "Green"}.issubset(top_colors)
