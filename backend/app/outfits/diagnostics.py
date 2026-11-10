"""Allowlisted diagnostics only: never serialize exception messages or responses."""
import re

CODES = {'insufficient_quota', 'rate_limit_exceeded', 'invalid_api_key',
         'credit_balance_exhausted', 'organization_spend_limit_exceeded',
         'project_spend_limit_exceeded', 'organization_usage_limit_exceeded',
         'slow_down', 'server_is_overloaded',
         'invalid_image', 'invalid_image_url', 'image_parse_error', 'image_too_large',
         'invalid_request_error', 'server_error', 'model_not_found',
         'context_length_exceeded', 'billing_hard_limit_reached'}
PHASES = {'generation', 'evaluation', 'clothing_generation', 'footwear_selection',
          'footwear_review', 'full_outfit_review', 'accessory_selection'}


class OutfitModelError(RuntimeError):
    def __init__(self, status, code=None, request_id=None, provider_message=None):
        super().__init__('Outfit model HTTP request failed')
        self.http_status = status
        self.provider_code = code if code in CODES else 'unknown'
        self.request_id = request_id if isinstance(request_id, str) and re.fullmatch(r'req_[a-zA-Z0-9_-]{1,100}', request_id) else None
        # Retained for explicitly redacted shadow-evaluation diagnostics only.
        # error_details() intentionally does not expose provider text in
        # production job records.
        self.provider_message = provider_message[:500] if isinstance(provider_message, str) else None


class OutfitValidationError(ValueError):
    def __init__(self, code):
        super().__init__('Outfit result validation failed')
        self.validation_code = code
        self.outfit_phase = {'too_many_proposals':'clothing_generation',
            'taste_exploration_quota_not_met':'clothing_generation',
            'invalid_footwear_selection':'footwear_selection',
            'invalid_accessory_selection':'accessory_selection',
            'invalid_footwear_review':'footwear_review',
            'invalid_full_review':'full_outfit_review',
            'garment_snapshot_changed':'full_outfit_review'}.get(code)


def error_details(error, phase=None):
    details = {'type': type(error).__name__}
    phase = phase or getattr(error, 'outfit_phase', None)
    if phase in PHASES: details['phase'] = phase
    if isinstance(error, OutfitModelError):
        details.update(http_status=error.http_status, provider_code=error.provider_code)
        if error.request_id: details['request_id'] = error.request_id
    if isinstance(error, OutfitValidationError) and error.validation_code in {
        'too_many_proposals', 'taste_exploration_quota_not_met', 'invalid_footwear_selection', 'invalid_footwear_review',
        'invalid_full_review', 'garment_snapshot_changed', 'invalid_accessory_selection'}:
        details['validation_code'] = error.validation_code
    return details
