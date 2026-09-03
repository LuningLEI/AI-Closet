from __future__ import annotations

import httpx

from app.services.weather_service import WeatherService


def test_weather_service_returns_fallback_when_location_and_weather_fail(monkeypatch) -> None:
    def fail_get(*args, **kwargs):
        raise httpx.ConnectError("network unavailable")

    monkeypatch.setattr(httpx, "get", fail_get)

    context = WeatherService().get_today_context()

    assert context["location"]["label"] == "Default weather context"
    assert context["location"]["source"] == "fallback"
    assert context["weather"]["temperature_f"] == 68
    assert context["weather"]["source"] == "fallback"


def test_weather_service_uses_manual_location_without_geocoding(monkeypatch) -> None:
    calls: list[tuple[float, float]] = []

    def fake_weather(self, latitude: float, longitude: float):
        calls.append((latitude, longitude))
        return {
            "temperature_f": 81,
            "feels_like_f": 81,
            "precipitation": 0,
            "wind_mph": 3,
            "condition": "Sunny",
            "weather_code": None,
            "source": "test-weather",
        }

    monkeypatch.setattr(WeatherService, "_weather", fake_weather)

    context = WeatherService().get_today_context(37.3382, -121.8863, location_label="San Jose, CA")

    assert calls == [(37.3382, -121.8863)]
    assert context["location"]["label"] == "San Jose, CA"
    assert context["location"]["source"] == "manual-location"
    assert context["weather"]["temperature_f"] == 81
