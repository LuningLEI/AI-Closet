from app.services.preference_schema import normalize_preference_record, normalize_preference_updates
from app.services.taxonomy import preferred_styles_for_occasion


def test_legacy_flat_styles_are_expanded_to_each_selected_occasion():
    result = normalize_preference_record({
        "user_id": "user-1",
        "preferences": {"profile": {
            "daily_occasions": ["Everyday", "Travel"],
            "style_preferences": ["Casual", "Sporty"],
        }},
    })

    assert result["occasion_style_preferences"] == {
        "Everyday": ["Casual", "Sporty"],
        "Travel": ["Casual", "Sporty"],
    }


def test_styles_are_saved_by_occasion_and_flat_field_is_compatibility_union():
    result = normalize_preference_updates("user-1", None, {
        "daily_occasions": ["Everyday", "Travel"],
        "occasion_style_preferences": {
            "Everyday": ["Classic", "Minimalist"],
            "Travel": ["Sporty"],
            "Work": ["Business"],
        },
    })

    assert result["occasion_style_preferences"] == {
        "Everyday": ["Classic", "Minimalist"],
        "Travel": ["Sporty"],
    }
    assert result["style_preferences"] == ["Classic", "Minimalist", "Sporty"]
    assert result["preferences"]["profile"]["occasion_style_preferences"] == result["occasion_style_preferences"]


def test_recommendation_resolves_only_the_requested_occasions_styles():
    preferences = {"profile": {
        "style_preferences": ["Classic", "Sporty"],
        "occasion_style_preferences": {
            "Everyday": ["Classic"],
            "Travel": ["Sporty", "Streetwear"],
        },
    }}

    assert preferred_styles_for_occasion(preferences, "travel") == ["Sporty", "Streetwear"]
    assert preferred_styles_for_occasion(preferences, "Work") == ["Classic", "Sporty"]
