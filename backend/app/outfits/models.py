from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
from app.models.domain import ClothingItemRecord

class Evaluation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    structurally_wearable: Literal['yes', 'no', 'cannot_judge']
    aesthetic_score: float | None = Field(ge=1, le=5, allow_inf_nan=False)
    structural_reason: str
    aesthetic_reason: str
    issues: list[str]

class VisualCriterion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    verdict: Literal['pass', 'fail', 'uncertain']
    reason: str

class VisualChecks(BaseModel):
    model_config = ConfigDict(extra='forbid')
    wearability: VisualCriterion
    thermal: VisualCriterion
    color_pattern: VisualCriterion
    occasion: VisualCriterion

    def passes(self):
        return all(getattr(self, name).verdict == 'pass' for name in type(self).model_fields)

class OptionalLayerReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    verdict: Literal['clear_improvement', 'no_improvement', 'uncertain', 'not_applicable']
    reason: str


class VisualReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    core: VisualChecks
    full: VisualChecks
    optional_layering: OptionalLayerReview = Field(default_factory=lambda: OptionalLayerReview(verdict="uncertain",reason="Optional layers have not been reviewed for visual improvement."))

    def diagnostic(self):
        checks = [getattr(self.core, name) for name in VisualChecks.model_fields]
        return Evaluation(structurally_wearable={'pass':'yes','fail':'no','uncertain':'cannot_judge'}[self.core.wearability.verdict],
            aesthetic_score=None, structural_reason=self.core.wearability.reason,
            aesthetic_reason='; '.join(c.reason for c in checks[1:]),
            issues=[c.reason for c in checks if c.verdict != 'pass'])

class CurrentVisualReview(VisualReview):
    # Required for fresh strict-schema model responses; old records parse as uncertain.
    optional_layering: OptionalLayerReview = Field(...)


class Proposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item_ids: list[str]
    reason: str

class Proposals(BaseModel):
    model_config = ConfigDict(extra='forbid')
    outfits: list[Proposal]

class OutfitVariantDTO(BaseModel):
    id: str
    items: list[ClothingItemRecord]
    visual_review_status: Literal['pending', 'passed'] = 'pending'
    liked: bool = False

class OutfitDTO(BaseModel):
    source: str = "generated"
    id: str
    items: list[ClothingItemRecord]
    optional_additions: list[OutfitVariantDTO] = Field(default_factory=list)
    aesthetic_score: float | None
    structural_reason: str
    aesthetic_reason: str
    visual_review_status: Literal['pending', 'passed'] = 'pending'
    liked: bool = False
    replaces_outfit_id: str | None = None

class LibraryResponse(BaseModel):
    outfits: list[OutfitDTO]
    total: int
    jobs: dict[str, int]
    enrolled: bool
    next_offset: int | None = None

class BuildRequest(BaseModel):
    anchor_item_id: str | None = None
    retry_failed: bool = False

class BuildResponse(BaseModel):
    queued: int
    jobs: dict[str, int]


class BatchAccessorySelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate_index: int = Field(ge=1)
    selected_shoe_id: str | None
    accessory_ids: list[str]
    reason: str


class BatchAccessorySelections(BaseModel):
    model_config = ConfigDict(extra='forbid')
    selections: list[BatchAccessorySelection]


class BatchVisualReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate_index: int = Field(ge=1)
    review: CurrentVisualReview


class OptionalItemDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item_id: str
    verdict: Literal['clear_improvement', 'no_improvement', 'uncertain']
    reason: str


class DetailedBatchVisualReview(BatchVisualReview):
    optional_item_reviews: list[OptionalItemDecision]


class BatchVisualReviews(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reviews: list[BatchVisualReview]


class DetailedBatchVisualReviews(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reviews: list[DetailedBatchVisualReview]
