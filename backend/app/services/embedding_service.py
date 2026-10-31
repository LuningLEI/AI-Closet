from __future__ import annotations

from typing import Any

from app.ai.gateway import AIGateway, build_ai_gateway
from app.core.config import settings
from app.core.constants import OPENAI_EMBEDDING_TIMEOUT_SECONDS
from app.models.domain import ClothingItemRecord, RecommendationContext


class EmbeddingService:
    def __init__(self, gateway: AIGateway | None = None) -> None:
        self.gateway = gateway or build_ai_gateway()

    def create_embedding(self, text: str) -> list[float] | None:
        embedding, _ = self.create_embedding_with_usage(text)
        return embedding

    def create_embedding_with_usage(self, text: str) -> tuple[list[float] | None, dict[str, Any] | None]:
        if not settings.ai_api_key:
            return None, None

        try:
            return self.gateway.embedding(model=settings.openai_embedding_model, text=text,
                                          dimensions=settings.openai_embedding_dimensions,
                                          timeout=OPENAI_EMBEDDING_TIMEOUT_SECONDS)
        except Exception as error:
            from app.core.observability import log_event
            log_event("ai.embedding_failed", provider=settings.ai_provider, error=type(error).__name__)
            return None, None


def item_embedding_text(item: ClothingItemRecord) -> str:
    return " ".join(
        value
        for value in [
            f"category: {item.category}",
            f"subtype: {item.subtype or 'none'}",
            f"fit: {item.fit}" if item.fit else "",
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
