"""Shared item commit shape; remote repositories execute it as one SQL transaction."""
from app.services.label_confirmation import COMPARE_FIELDS


def expected_item(item):
    fields = set(COMPARE_FIELDS) | {'id','user_id','pattern','fit','neckline','layering_role',
                                  'warmth_level','formality_score','recognition_tags'}
    return {key: getattr(item,key) for key in fields}
