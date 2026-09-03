from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.constants import OPENAI_EMBEDDING_TIMEOUT_SECONDS
from app.models.domain import ClothingItemRecord, RecommendationContext


class EmbeddingService:
    def create_embedding(self, text: str) -> list[float] | None:
        if not settings.openai_api_key:
            return None

        try:
            response = httpx.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_embedding_model,
                    "input": text,
                    "dimensions": settings.openai_embedding_dimensions,
                },
                timeout=OPENAI_EMBEDDING_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            return [float(value) for value in payload["data"][0]["embedding"]]
        except Exception as error:
            print("OPENAI EMBEDDING FAILED:", error)
            return None


def item_embedding_text(item: ClothingItemRecord) -> str:
    return " ".join(
        value
        for value in [
            f"category: {item.category}",
            f"subtype: {item.subtype or 'none'}",
            f"color: {item.color}",
            f"season: {item.season}",
            f"style: {item.style}",
            f"occasion: {item.occasion}",
            f"description: {item.recognition_summary or ''}",
        ]
        if value
    )


def recommendation_context_text(context: RecommendationContext) -> str:
    return " ".join(
        value
        for value in [
            f"occasion: {context.occasion}",
            f"temperature fahrenheit: {context.temperature_f}",
            f"preferred style: {context.preferred_style or 'any'}",
            f"preferred color: {context.preferred_color or 'any'}",
            "Find compatible wearable outfit pieces, including possible layered tops and outerwear.",
        ]
        if value
    )
