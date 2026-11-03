from app.services.preference_schema import normalize_preference_record, normalize_preference_updates
from app.services.taxonomy import preferred_styles_for_occasion
from app.services.personalization_settings import (
    effective_temperature_f,
    exploration_rate,
    resolve_personalization_settings,
)


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


def test_personalization_controls_round_trip_through_preferences_json():
    result = normalize_preference_updates("user-1", None, {
        "personalization_enabled": False,
        "feedback_learning_enabled": False,
        "exploration_level": "adventurous",
        "rotation_level": "more_variety",
        "temperature_sensitivity": "runs_cold",
    })

    assert result["personalization_enabled"] is False
    assert result["feedback_learning_enabled"] is False
    assert result["preferences"]["recommendation"] == {
        "personalization_enabled": False,
        "feedback_learning_enabled": False,
        "exploration_level": "adventurous",
        "rotation_level": "more_variety",
        "temperature_sensitivity": "runs_cold",
    }


def test_user_facing_levels_map_to_server_owned_numeric_policy():
    familiar = resolve_personalization_settings({"recommendation": {"exploration_level": "familiar"}})
    balanced = resolve_personalization_settings(None)
    adventurous = resolve_personalization_settings({"recommendation": {"exploration_level": "adventurous"}})

    assert [exploration_rate(value) for value in (familiar, balanced, adventurous)] == [0.0, 0.15, 0.30]
    assert effective_temperature_f(62, resolve_personalization_settings({
        "recommendation": {"temperature_sensitivity": "runs_cold"}
    })) == 57
    assert effective_temperature_f(62, resolve_personalization_settings({
        "recommendation": {"temperature_sensitivity": "runs_warm"}
    })) == 67
