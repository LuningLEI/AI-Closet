from __future__ import annotations
import base64
import json
from pathlib import Path
from app.ai.gateway import AIGateway, build_ai_gateway
from app.outfits.models import Proposals, CurrentVisualReview, BatchAccessorySelections, BatchVisualReviews
from app.outfits.compatibility import core_items, optional_layer_ids
from app.services.storage_service import StorageService
from app.services.taste_profile import generation_taste_context

class VisionOutfitProvider:
    """Provider boundary: replace this class to use a different vendor/API."""
    def __init__(self, config, storage=None, gateway: AIGateway | None = None):
        self.config = config
        self.storage = storage or StorageService()
        self.gateway = gateway or build_ai_gateway()

    def images(self, items):
        content = []
        for item in items:
            url = self.storage.signed_image_url(item.image_path, expires_in=3600)
            if not url or not url.startswith('https://'):
                path = Path(item.image_path or '')
                if not path.is_file():
                    raise ValueError('An outfit image is unavailable')
                mime = 'image/png' if path.suffix.lower() == '.png' else 'image/jpeg'
                url = f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode()
            content.extend([
                {'type': 'input_text', 'text': json.dumps({k: getattr(item, k) for k in
                    ['id', 'category', 'subtype', 'color', 'style', 'material', 'pattern', 'fit', 'length', 'sleeve_length', 'layering_role', 'wearing_profile', 'color_tones', 'warmth_level', 'formality_score', 'occasion', 'season']})},
                {'type': 'input_image', 'image_url': url, 'detail': self.config.image_detail},
            ])
        return content

    @staticmethod
    def unique_items(groups):
        unique = {}
        for group in groups:
            for item in group:
                unique.setdefault(item.id, item)
        return list(unique.values())

    def metadata(self, items):
        fields = ['id', 'category', 'subtype', 'color', 'style', 'material', 'pattern',
                  'fit', 'length', 'sleeve_length', 'layering_role', 'wearing_profile', 'color_tones', 'warmth_level',
                  'formality_score', 'occasion', 'season']
        return [{'type':'input_text', 'text':json.dumps({k:getattr(item,k) for k in fields})} for item in items]

    def request(self, model, prompt, content, output_type):
        result = self.gateway.response(model=model, input=[
            {'role': 'system', 'content': prompt}, {'role': 'user', 'content': content}],
            schema=output_type, timeout=self.config.request_timeout_seconds)
        return output_type.model_validate_json(result.text), result.usage

    def generate(self, anchor, catalog):
        message = {'anchor_item_id': anchor.id, 'require_shoes': self.config.require_shoes,
                   'maximum_outfits': self.config.candidates_per_anchor,
                   'maximum_items_per_outfit': self.config.max_items_per_outfit}
        return self.request(self.config.generation_model, self.config.generation_text,
            [{'type': 'input_text', 'text': json.dumps(message)}] + self.images(catalog), Proposals)

    def evaluate(self, items):
        roles = {'require_shoes': self.config.require_shoes,
                 'core_item_ids': [i.id for i in core_items(items, require_shoes=self.config.require_shoes)],
                 'full_item_ids': [i.id for i in items],
                 'optional_layer_item_ids': optional_layer_ids(items, require_shoes=self.config.require_shoes)}
        return self.request(self.config.evaluation_model, self.config.evaluation_text,
            [{'type': 'input_text', 'text': json.dumps(roles)}] + self.images(items), CurrentVisualReview)

    def generate_clothing(self, anchor, catalog):
        message = {'anchor_item_id': anchor.id if anchor.category != 'Shoes' and not (self.config.accessory_pipeline and anchor.category in {'Accessories', 'Bags'}) else None,
                   'maximum_outfits': self.config.candidates_per_anchor,
                   'maximum_items_per_outfit': self.config.max_items_per_outfit - 1}
        self.generation_taste_context=generation_taste_context(
            anchor,catalog,getattr(self,'taste_profile',None),self.config.candidates_per_anchor)
        if self.generation_taste_context:
            message['learned_taste']=self.generation_taste_context
        return self.request(self.config.generation_model, self.config.clothing_text,
            [{'type':'input_text','text':json.dumps(message)}] + self.images(catalog), Proposals)

    def select_accessories_batch(self, candidates):
        contexts = []
        groups = []
        for candidate_index, clothing, shoes, accessories in candidates:
            contexts.append({'candidate_index': candidate_index,
                'clothing_item_ids': [i.id for i in clothing],
                'candidate_shoe_ids': [i.id for i in shoes],
                'candidate_accessory_ids': [i.id for i in accessories],
                'maximum_accessories': max(0, self.config.max_items_per_outfit-len(clothing)-1)})
            groups.extend((clothing, shoes, accessories))
        instruction = ('\nBATCH MODE: Return exactly one selection for every supplied candidate_index. '
            'Judge each candidate independently and use only the shoe/accessory IDs listed for that candidate.')
        return self.request(self.config.footwear_selection_model,
            self.config.accessory_selection_text + instruction,
            [{'type':'input_text','text':json.dumps({'candidates': contexts})}] +
            self.images(self.unique_items(groups)), BatchAccessorySelections)

    def evaluate_batch(self, candidates):
        contexts = []
        groups = []
        for candidate_index, items in candidates:
            contexts.append({'candidate_index': candidate_index,
                'require_shoes': self.config.require_shoes,
                'core_item_ids': [i.id for i in core_items(items, require_shoes=self.config.require_shoes)],
                'full_item_ids': [i.id for i in items],
                'optional_layer_item_ids': optional_layer_ids(items, require_shoes=self.config.require_shoes)})
            groups.append(items)
        memory=(getattr(self,'taste_profile',None) or {}).get('generation_memory') or {}
        payload={'candidates': contexts}
        profile=getattr(self,'taste_profile',None) or {}
        if memory.get('evidence_threshold_met') or profile.get('free_text_summary'):
            payload['learned_taste']={'prefer':memory.get('preferred',[]),'avoid':memory.get('avoid',[]),
                'free_text_summary':profile.get('free_text_summary') or {}}
        instruction = ('\nBATCH MODE: Review every supplied candidate_index independently. Return exactly one '
            'review for each candidate_index. Do not transfer garments or conclusions between candidates.')
        return self.request(self.config.evaluation_model, self.config.evaluation_text + instruction,
            [{'type':'input_text','text':json.dumps(payload)}] +
            self.images(self.unique_items(groups)), BatchVisualReviews)
