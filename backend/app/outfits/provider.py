from __future__ import annotations
import base64
import io
import json
import math
from pathlib import Path
import httpx
from PIL import Image, ImageDraw, ImageOps
from app.ai.gateway import (
    AIGateway, build_outfit_generation_gateway, build_outfit_visual_gateway,
)
from app.outfits.models import (
    Proposals, CurrentVisualReview, BatchAccessorySelections, BatchVisualReviews,
    DetailedBatchVisualReviews,
)
from app.outfits.compatibility import core_items, optional_layer_ids
from app.services.storage_service import StorageService
from app.services.taste_profile import generation_taste_context


QWEN_METADATA_CLOTHING_POLICY = """

METADATA-ONLY GENERATION MODE:
- No garment images are supplied in this generation stage. Use only supplied IDs and structured metadata; never claim visual inspection.
- For a Bottoms anchor, first form a complete base with exactly one independently wearable base Top.
- A second Tops-slot garment is optional upper layering, not another required core piece. Include it only for a clear, non-redundant and physically compatible purpose.
- Return at most two layered proposals containing two Tops-slot garments for one Bottoms anchor; keep the other proposals single-top bases.
- For Activewear Bottoms, prefer supplied Activewear and genuinely sport-compatible tops before general casual tops. Do not use a formal blouse or statement top just because vector/color evidence is close.
- Metadata is fallible. Return fewer proposals rather than inventing construction, fit or compatibility.
"""

class VisionOutfitProvider:
    """Provider boundary: replace this class to use a different vendor/API."""
    def __init__(self, config, storage=None, gateway: AIGateway | None = None,
                 generation_gateway: AIGateway | None = None,
                 visual_gateway: AIGateway | None = None):
        self.config = config
        self.storage = storage or StorageService()
        self.generation_gateway = generation_gateway or gateway or build_outfit_generation_gateway()
        self.visual_gateway = visual_gateway or gateway or build_outfit_visual_gateway()
        self.image_client = httpx.Client(http2=False)

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

    def request(self, model, prompt, content, output_type, schema=None):
        generation_only = (
            model == self.config.generation_model
            and model not in {self.config.evaluation_model, self.config.footwear_selection_model}
        )
        gateway = self.generation_gateway if generation_only else self.visual_gateway
        result = gateway.response(model=model, input=[
            {'role': 'system', 'content': prompt}, {'role': 'user', 'content': content}],
            schema=schema or output_type, timeout=self.config.request_timeout_seconds)
        return output_type.model_validate_json(result.text), result.usage

    def _source_image(self, item):
        url = self.storage.signed_image_url(item.image_path, expires_in=3600)
        if url and url.startswith('https://'):
            response = self.image_client.get(url, timeout=self.config.request_timeout_seconds)
            response.raise_for_status()
            source = Image.open(io.BytesIO(response.content))
        else:
            path = Path(item.image_path or '')
            if not path.is_file():
                raise ValueError('An outfit image is unavailable')
            source = Image.open(path)
        source.load()
        return ImageOps.exif_transpose(source).convert('RGB')

    @staticmethod
    def _label(item):
        return f'{item.subtype or item.category} | {item.color or "Unknown"} | {item.id[:8]}'

    def _composite(self, sections):
        tile, label_height, heading_height, gap, columns = 250, 42, 42, 12, 4
        sections = [(heading, rows) for heading, rows in sections if rows]
        width = columns * tile + (columns + 1) * gap
        height = gap + sum(
            heading_height + math.ceil(len(rows) / columns) * (tile + label_height + gap)
            for _, rows in sections
        )
        canvas = Image.new('RGB', (width, height), 'white'); draw = ImageDraw.Draw(canvas); y = gap
        for heading, rows in sections:
            draw.rectangle((0, y, width, y + heading_height), fill='#e8eef6')
            draw.text((gap, y + 12), heading, fill='black'); y += heading_height
            for index, item in enumerate(rows):
                column, row = index % columns, index // columns
                x = gap + column * (tile + gap); item_y = y + row * (tile + label_height + gap)
                fitted = ImageOps.fit(self._source_image(item), (tile, tile), Image.Resampling.LANCZOS)
                canvas.paste(fitted, (x, item_y))
                draw.rectangle((x, item_y, x + tile - 1, item_y + tile - 1), outline='#707070', width=2)
                draw.text((x + 5, item_y + tile + 7), self._label(item), fill='black')
            y += math.ceil(len(rows) / columns) * (tile + label_height + gap)
        if max(canvas.size) > self.config.composite_max_dimension:
            canvas.thumbnail((self.config.composite_max_dimension, self.config.composite_max_dimension), Image.Resampling.LANCZOS)
        buffer = io.BytesIO(); canvas.save(buffer, format='JPEG', quality=90, optimize=True)
        return 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')

    @staticmethod
    def _batch_schema(output_type, count, candidate_indexes, optional_ids=None):
        schema = output_type.model_json_schema()
        schema['properties']['selections' if 'selections' in schema['properties'] else 'reviews']['minItems'] = count
        schema['properties']['selections' if 'selections' in schema['properties'] else 'reviews']['maxItems'] = count
        definition = 'BatchAccessorySelection' if 'selections' in schema['properties'] else (
            'DetailedBatchVisualReview' if 'DetailedBatchVisualReview' in schema.get('$defs', {}) else 'BatchVisualReview'
        )
        schema['$defs'][definition]['properties']['candidate_index'] = {'type':'integer','enum':candidate_indexes}
        if optional_ids and 'OptionalItemDecision' in schema.get('$defs', {}):
            schema['$defs']['OptionalItemDecision']['properties']['item_id'] = {
                'type':'string','enum':list(dict.fromkeys(optional_ids)),
            }
        return schema

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
        content = self.metadata(catalog) if self.config.clothing_input_mode == 'metadata-only' else self.images(catalog)
        prompt = self.config.clothing_text
        if self.config.clothing_input_mode == 'metadata-only':
            prompt += QWEN_METADATA_CLOTHING_POLICY
        return self.request(self.config.generation_model, prompt,
            [{'type':'input_text','text':json.dumps(message)}] + content, Proposals)

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
        if self.config.composite_visual_inputs:
            content = [{'type':'input_text','text':json.dumps({'candidates': contexts})}]
            for _, clothing, shoes, accessories in candidates:
                content.append({'type':'input_image','image_url':self._composite([
                    ('CLOTHING BASE',clothing),('SHOE CANDIDATES',shoes),
                    ('OPTIONAL BAGS / ACCESSORIES',accessories),
                ]),'detail':'high'})
            instruction += (' Each supplied image is one labeled candidate board in the same order. '
                'Compare color-responsive options against the whole outfit; do not default to neutral black.')
            indexes = [row[0] for row in candidates]
            return self.request(self.config.footwear_selection_model,
                self.config.accessory_selection_text + instruction, content, BatchAccessorySelections,
                self._batch_schema(BatchAccessorySelections,len(indexes),indexes))
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
        if self.config.composite_visual_inputs:
            content = [{'type':'input_text','text':json.dumps(payload)}]
            for candidate_index, items in candidates:
                content.extend([
                    {'type':'input_text','text':json.dumps({'candidate_index':candidate_index,
                        'items':[{k:getattr(item,k) for k in ['id','category','subtype','color','style','material','pattern','fit','length','warmth_level','formality_score','occasion','season']} for item in items]})},
                    {'type':'input_image','image_url':self._composite([('COMPLETE OUTFIT',items)]),'detail':'high'},
                ])
            output_type = DetailedBatchVisualReviews if self.config.per_optional_item_review else BatchVisualReviews
            optional_ids = [item_id for row in contexts for item_id in row['optional_layer_item_ids']]
            if self.config.per_optional_item_review:
                instruction += (' Return one optional_item_reviews entry for every supplied optional layer ID in order. '
                    'Judge each independently. Accessories require clear visual improvement; one good item cannot rescue another. '
                    'Compatible outerwear may be no_improvement when it remains useful as a colder-temperature variant.')
            indexes = [row[0] for row in candidates]
            return self.request(self.config.evaluation_model, self.config.evaluation_text + instruction,
                content, output_type, self._batch_schema(output_type,len(indexes),indexes,optional_ids))
        return self.request(self.config.evaluation_model, self.config.evaluation_text + instruction,
            [{'type':'input_text','text':json.dumps(payload)}] +
            self.images(self.unique_items(groups)), BatchVisualReviews)
