from __future__ import annotations

from typing import Any

import httpx

from app.core.constants import (
    DEFAULT_LOCATION_LABEL,
    DEFAULT_LOCATION_LATITUDE,
    DEFAULT_LOCATION_LONGITUDE,
    DEFAULT_TEMPERATURE_F,
    HTTP_NOT_FOUND,
    OPEN_METEO_CLEAR_CODES,
    OPEN_METEO_FOG_CODES,
    OPEN_METEO_PARTLY_CLOUDY_CODES,
    OPEN_METEO_RAIN_CODES,
    OPEN_METEO_SNOW_CODES,
    OPEN_METEO_STORM_CODES,
    WEATHER_HTTP_TIMEOUT_SECONDS,
    WeatherCondition,
    WeatherSource,
)


class WeatherService:
    def get_today_context(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
        location_query: str | None = None,
        location_label: str | None = None,
    ) -> dict[str, Any]:
        location = self._location(latitude, longitude, location_query, location_label)
        weather = self._weather(location["latitude"], location["longitude"])
        return {"location": location, "weather": weather}

    def _location(
        self,
        latitude: float | None,
        longitude: float | None,
        location_query: str | None,
        location_label: str | None,
    ) -> dict[str, Any]:
        if latitude is not None and longitude is not None and location_label:
            return {
                "label": location_label,
                "detail": self._coordinate_detail(latitude, longitude),
                "latitude": latitude,
                "longitude": longitude,
                "source": WeatherSource.MANUAL_LOCATION,
            }

        if location_query:
            geocoded_location = self._geocode_location(location_query)
            if geocoded_location:
                return geocoded_location
            raise ValueError(f'Could not find weather location "{location_query}".')

        if latitude is not None and longitude is not None:
            reverse_location = self._reverse_geocode(latitude, longitude)
            coordinate_detail = self._coordinate_detail(latitude, longitude)
            return {
                "label": reverse_location or "Current location",
                "detail": coordinate_detail,
                "latitude": latitude,
                "longitude": longitude,
                "source": WeatherSource.BROWSER_GEOLOCATION,
            }

        try:
            response = httpx.get("https://ipapi.co/json/", timeout=WEATHER_HTTP_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            latitude = float(payload["latitude"])
            longitude = float(payload["longitude"])
            return {
                "label": ", ".join(part for part in [payload.get("city"), payload.get("region"), payload.get("country_name")] if part) or "Network location",
                "detail": self._coordinate_detail(latitude, longitude),
                "latitude": latitude,
                "longitude": longitude,
                "source": WeatherSource.IP_GEOLOCATION,
            }
        except Exception as error:
            print("LOCATION LOOKUP FAILED:", error)
            return {
                "label": DEFAULT_LOCATION_LABEL,
                "detail": self._coordinate_detail(DEFAULT_LOCATION_LATITUDE, DEFAULT_LOCATION_LONGITUDE),
                "latitude": DEFAULT_LOCATION_LATITUDE,
                "longitude": DEFAULT_LOCATION_LONGITUDE,
                "source": WeatherSource.FALLBACK,
            }

    def _geocode_location(self, location_query: str) -> dict[str, Any] | None:
        nominatim_location = self._geocode_with_nominatim(location_query)
        if nominatim_location:
            return nominatim_location

        return self._geocode_with_open_meteo(location_query)

    def _geocode_with_nominatim(self, location_query: str) -> dict[str, Any] | None:
        try:
            response = httpx.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": location_query,
                    "format": "jsonv2",
                    "addressdetails": 1,
                    "limit": 5,
                    "countrycodes": "us",
                },
                headers={"User-Agent": "ai-closet-local-dev/1.0"},
                timeout=WEATHER_HTTP_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            results = response.json()
            if not results:
                return None

            result = self._best_nominatim_result(results, location_query)
            latitude = float(result["lat"])
            longitude = float(result["lon"])
            address = result.get("address", {})
            label = ", ".join(
                part
                for part in [
                    address.get("city") or address.get("town") or address.get("village") or result.get("name"),
                    address.get("state"),
                    address.get("country"),
                ]
                if part
            )
            return {
                "label": label or result.get("display_name") or location_query,
                "detail": self._coordinate_detail(latitude, longitude),
                "latitude": latitude,
                "longitude": longitude,
                "source": WeatherSource.MANUAL_LOCATION,
            }
        except Exception as error:
            print("NOMINATIM GEOCODING FAILED:", error)
            return None

    def _best_nominatim_result(self, results: list[dict[str, Any]], location_query: str) -> dict[str, Any]:
        normalized_query = location_query.lower()
        if "ca" in normalized_query or "california" in normalized_query:
            for result in results:
                address = result.get("address", {})
                city = (address.get("city") or address.get("town") or address.get("village") or "").lower()
                state = (address.get("state") or "").lower()
                if "san jose" in city and state == "california":
                    return result
        return results[0]

    def _geocode_with_open_meteo(self, location_query: str) -> dict[str, Any] | None:
        try:
            response = httpx.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": location_query, "count": 1, "language": "en", "format": "json"},
                timeout=WEATHER_HTTP_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            results = response.json().get("results") or []
            if not results:
                return None
            result = results[0]
            latitude = float(result["latitude"])
            longitude = float(result["longitude"])
            label = ", ".join(
                part
                for part in [
                    result.get("name"),
                    result.get("admin1"),
                    result.get("country"),
                ]
                if part
            )
            return {
                "label": label or location_query,
                "detail": self._coordinate_detail(latitude, longitude),
                "latitude": latitude,
                "longitude": longitude,
                "source": WeatherSource.MANUAL_LOCATION,
            }
        except Exception as error:
            print("OPEN-METEO GEOCODING FAILED:", error)
            return None

    def _reverse_geocode(self, latitude: float, longitude: float) -> str | None:
        try:
            response = httpx.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={
                    "format": "jsonv2",
                    "lat": latitude,
                    "lon": longitude,
                    "zoom": 10,
                    "addressdetails": 1,
                },
                headers={"User-Agent": "ai-closet-local-dev/1.0"},
                timeout=WEATHER_HTTP_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            address = response.json().get("address", {})
            city = address.get("city") or address.get("town") or address.get("village") or address.get("municipality") or address.get("county")
            region = address.get("state")
            country = address.get("country")
            return ", ".join(part for part in [city, region, country] if part) or None
        except Exception as error:
            print("REVERSE GEOCODING FAILED:", error)
            return None

    def _coordinate_detail(self, latitude: float, longitude: float) -> str:
        return f"{latitude:.4f}, {longitude:.4f}"

    def _weather(self, latitude: float, longitude: float) -> dict[str, Any]:
        nws_weather = self._weather_gov(latitude, longitude)
        if nws_weather:
            return nws_weather

        try:
            response = httpx.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
                    "temperature_unit": "fahrenheit",
                    "wind_speed_unit": "mph",
                    "timezone": "auto",
                },
                timeout=WEATHER_HTTP_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            current = response.json().get("current", {})
            code = int(current.get("weather_code") or 0)
            return {
                "temperature_f": float(current.get("temperature_2m") or DEFAULT_TEMPERATURE_F),
                "feels_like_f": float(current.get("apparent_temperature") or current.get("temperature_2m") or DEFAULT_TEMPERATURE_F),
                "precipitation": float(current.get("precipitation") or 0),
                "wind_mph": float(current.get("wind_speed_10m") or 0),
                "condition": self._condition(code),
                "weather_code": code,
                "source": WeatherSource.OPEN_METEO,
            }
        except Exception as error:
            print("WEATHER LOOKUP FAILED:", error)
            return {
                "temperature_f": DEFAULT_TEMPERATURE_F,
                "feels_like_f": DEFAULT_TEMPERATURE_F,
                "precipitation": 0,
                "wind_mph": 0,
                "condition": WeatherCondition.MILD,
                "weather_code": None,
                "source": WeatherSource.FALLBACK,
            }

    def _weather_gov(self, latitude: float, longitude: float) -> dict[str, Any] | None:
        try:
            headers = {"User-Agent": "ai-closet-local-dev/1.0"}
            points_response = httpx.get(
                f"https://api.weather.gov/points/{latitude:.4f},{longitude:.4f}",
                headers=headers,
                timeout=WEATHER_HTTP_TIMEOUT_SECONDS,
            )
            if points_response.status_code == HTTP_NOT_FOUND:
                return None
            points_response.raise_for_status()
            properties = points_response.json().get("properties", {})
            hourly_url = properties.get("forecastHourly")
            if not hourly_url:
                return None

            forecast_response = httpx.get(hourly_url, headers=headers, timeout=WEATHER_HTTP_TIMEOUT_SECONDS)
            forecast_response.raise_for_status()
            periods = forecast_response.json().get("properties", {}).get("periods", [])
            current = periods[0] if periods else {}
            temperature = float(current.get("temperature") or DEFAULT_TEMPERATURE_F)
            condition = current.get("shortForecast") or WeatherCondition.MILD
            return {
                "temperature_f": temperature,
                "feels_like_f": temperature,
                "precipitation": None,
                "wind_mph": self._wind_speed_mph(current.get("windSpeed")),
                "condition": condition,
                "weather_code": None,
                "source": WeatherSource.WEATHER_GOV,
            }
        except Exception as error:
            print("WEATHER.GOV LOOKUP FAILED:", error)
            return None

    def _wind_speed_mph(self, wind_speed: str | None) -> float | None:
        if not wind_speed:
            return None
        for part in wind_speed.split():
            if part.isdigit():
                return float(part)
        return None

    def _condition(self, code: int) -> str:
        if code in OPEN_METEO_CLEAR_CODES:
            return WeatherCondition.CLEAR
        if code in OPEN_METEO_PARTLY_CLOUDY_CODES:
            return WeatherCondition.PARTLY_CLOUDY
        if code in OPEN_METEO_FOG_CODES:
            return WeatherCondition.FOGGY
        if code in OPEN_METEO_RAIN_CODES:
            return WeatherCondition.RAINY
        if code in OPEN_METEO_SNOW_CODES:
            return WeatherCondition.SNOWY
        if code in OPEN_METEO_STORM_CODES:
            return WeatherCondition.STORMY
        return WeatherCondition.MILD
