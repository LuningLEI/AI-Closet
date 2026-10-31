from uuid import uuid4

import pytest

from app.outfits.config import load_config
from app.outfits.models import Proposal, Proposals


class CurrentPipelineProvider:
    def __init__(self, top, bottom, shoe):
        self.top = top
        self.bottom = bottom
        self.shoe = shoe
        self.calls = []

    def generate_clothing(self, anchor, catalog):
        assert all(item.category != 'Shoes' for item in catalog)
        self.calls.append('clothing')
        ids = [self.top.id, self.bottom.id]
        return Proposals(outfits=[
            Proposal(item_ids=ids, reason='Clothing first'),
            Proposal(item_ids=ids[::-1], reason='duplicate'),
        ]), {}


@pytest.fixture
def pipeline(setup):
    uid, top, bottom, library, _ = setup
    library.config = load_config()
    shoe = top.model_copy(update={'id': str(uuid4()), 'category': 'Shoes', 'subtype': 'Flats'})
    alternative = shoe.model_copy(update={'id': str(uuid4()), 'subtype': 'Boots'})
    for item in [shoe, alternative]:
        library.repository.add_item(item)
    provider = CurrentPipelineProvider(top, bottom, shoe)
    library.provider = provider
    return uid, top, bottom, shoe, alternative, library, provider
