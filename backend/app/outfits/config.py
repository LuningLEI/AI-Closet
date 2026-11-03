from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import Literal

from app.services.layering_fit import LayeringFitPolicy

HERE = Path(__file__).resolve().parent

def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

class CompatibilityRules(BaseModel):
    model_config = ConfigDict(extra='forbid')
    block_double_statement_patterns: bool = True
    block_thermal_conflicts: bool = True
    block_purpose_conflicts: bool = True
    very_warm_minimum: int = Field(default=5, ge=2, le=5)
    very_light_maximum: int = Field(default=1, ge=1, le=4)

    @model_validator(mode='after')
    def separated_extremes(self):
        if self.very_light_maximum >= self.very_warm_minimum:
            raise ValueError('Thermal conflict bounds must not overlap')
        return self

class CatalogRules(BaseModel):
    model_config = ConfigDict(extra='forbid')
    incompatible_style_pairs: list[tuple[str,str]] = Field(default_factory=lambda: [('Business','Sporty'),('Formal','Sporty')])
    metadata_weight: float = Field(default=0.25, ge=0, le=2, allow_inf_nan=False)
    preference_weight: float = Field(default=0.15, ge=0, le=2, allow_inf_nan=False)

class ModelPricing(BaseModel):
    model_config = ConfigDict(extra='forbid')
    input_per_million: float = Field(ge=0,allow_inf_nan=False)
    cached_input_per_million: float = Field(ge=0,allow_inf_nan=False)
    output_per_million: float = Field(ge=0,allow_inf_nan=False)
    source: str = Field(min_length=1)
    as_of: str = Field(min_length=1)

class OutfitConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pricing: dict[str, ModelPricing] = Field(default_factory=dict)
    catalog_rules: CatalogRules = Field(default_factory=CatalogRules)
    generation_model: str
    evaluation_model: str
    image_detail: Literal['low', 'high', 'auto'] = 'low'
    compatibility_rules: CompatibilityRules = Field(default_factory=CompatibilityRules)
    layering_fit_policy: LayeringFitPolicy = Field(default_factory=LayeringFitPolicy)
    pipeline_mode: Literal['vision_then_visual'] = 'vision_then_visual'
    visual_review_prompt: str = 'prompts/review_visual.txt'
    # Missing in archived run snapshots: retain their historical policy.
    require_shoes: bool = True
    footwear_pipeline: bool = True
    accessory_pipeline: bool = True
    accessory_catalog_limit: int = Field(default=8, ge=0, le=30)
    # Execution-only caps. Archived run snapshots omit these fields and therefore
    # automatically receive the safer/cost-bounded defaults when resumed.
    vision_accessory_limit: int = Field(default=4, ge=0, le=8)
    accessory_selection_prompt: str = 'prompts/select_accessories.txt'
    accessory_selection_text: str = ''
    footwear_catalog_limit: int = Field(default=8, ge=1, le=30)
    vision_footwear_limit: int = Field(default=4, ge=1, le=8)
    footwear_selection_model: str = 'gpt-4.1-mini'
    clothing_prompt: str = 'prompts/generate_clothing.txt'
    footwear_selection_prompt: str = 'prompts/select_footwear.txt'
    clothing_text: str = ''
    footwear_selection_text: str = ''
    catalog_limit: int = Field(default=40, ge=2, le=120)
    candidates_per_anchor: int = Field(default=8, ge=1, le=30)
    max_items_per_outfit: int = Field(default=4, ge=2, le=6)
    request_timeout_seconds: int = Field(default=120, ge=10, le=300)
    lease_seconds: int = Field(default=1800, ge=60, le=14400)
    max_attempts: int = Field(default=3, ge=1, le=10)
    poll_seconds: float = Field(default=5, ge=1, le=60)
    generation_prompt: str
    evaluation_prompt: str
    generation_text: str = ''
    evaluation_text: str = ''

    @model_validator(mode='after')
    def lease_covers_work(self):
        calls_per_job = 3
        if self.lease_seconds <= calls_per_job * self.request_timeout_seconds + 60:
            raise ValueError('lease_seconds must cover all generation/evaluation requests plus 60 seconds')
        return self

    @property
    def evaluator_key(self):
        return digest([self.evaluation_model, self.evaluation_text, self.image_detail,
                       'accessories-full-review-v1', self.require_shoes])

    @property
    def generation_key(self):
        # Threshold changes reuse saved ratings; model/prompt/catalog changes enqueue a new pass.
        base = [self.generation_model, self.generation_text, self.evaluator_key,
                       self.catalog_limit, self.candidates_per_anchor, self.max_items_per_outfit, 'outfit-core-vision-v1',
                       'vector-catalog-v4-thermal-standalone-outerwear', self.require_shoes, self.catalog_rules.model_dump(),
                       self.layering_fit_policy.model_dump(),
                       self.footwear_pipeline,self.clothing_text,self.footwear_catalog_limit,
                       self.footwear_selection_model,self.footwear_selection_text]
        base += ['accessories-v1', self.accessory_catalog_limit, self.accessory_selection_text]
        return digest(base)

    def snapshot(self):
        return self.model_dump()

def load_config() -> OutfitConfig:
    path = Path(os.environ.get('OUTFIT_CONFIG_PATH', HERE / 'config.json')).resolve()
    values = json.loads(path.read_text())
    values['generation_text'] = (path.parent / values['generation_prompt']).read_text()
    values['evaluation_text'] = (path.parent / values.get(
        'visual_review_prompt', OutfitConfig.model_fields['visual_review_prompt'].default)).read_text()
    if values.get('footwear_pipeline', False):
        for key in ('clothing', 'footwear_selection'):
            prompt = values.get(key + '_prompt', OutfitConfig.model_fields[key + '_prompt'].default)
            values[key + '_text'] = (path.parent / prompt).read_text()
    if values.get('accessory_pipeline', False):
        prompt = values.get('accessory_selection_prompt', OutfitConfig.model_fields['accessory_selection_prompt'].default)
        values['accessory_selection_text'] = (path.parent / prompt).read_text()
    return OutfitConfig.model_validate(values)
