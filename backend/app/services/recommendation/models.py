from __future__ import annotations

from dataclasses import dataclass

from app.models.domain import ClothingItemRecord


@dataclass
class Candidate:
    top: ClothingItemRecord | None = None
    bottom: ClothingItemRecord | None = None
    full_body: ClothingItemRecord | None = None
    shoes: ClothingItemRecord | None = None
    outerwear: ClothingItemRecord | None = None
    accessory: ClothingItemRecord | None = None

    @property
    def items(self) -> list[ClothingItemRecord]:
        return [
            item
            for item in [
                self.full_body,
                self.top,
                self.bottom,
                self.shoes,
                self.outerwear,
                self.accessory,
            ]
            if item
        ]

    @property
    def identifier(self) -> str:
        return "-".join(item.id for item in self.items)

    @property
    def has_any_top(self) -> bool:
        return self.top is not None

    @property
    def has_core_outfit(self) -> bool:
        return self.full_body is not None or (self.has_any_top and self.bottom is not None)

    @property
    def has_shoes(self) -> bool:
        return self.shoes is not None

    @property
    def is_complete_outfit(self) -> bool:
        return self.has_core_outfit and self.has_shoes

    @property
    def lead_item_id(self) -> str | None:
        lead = self.full_body or self.top or self.bottom or self.shoes
        return lead.id if lead else None

    @property
    def structure_signature(self) -> str:
        slots = [
            ("full_body", self.full_body),
            ("top", self.top),
            ("bottom", self.bottom),
            ("shoes", self.shoes),
            ("outerwear", self.outerwear),
            ("accessory", self.accessory),
        ]
        return "|".join(f"{slot}:{item.id}" for slot, item in slots if item is not None)
