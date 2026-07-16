"""Generated from contracts/review_contract.json. Do not edit by hand."""

CONTRACT_ID = 'catalyst-data-review/1.0'
CONFIDENCE_MINIMUM = 0
CONFIDENCE_MAXIMUM = 100
NEEDS_EVIDENCE_BELOW = 40
CAUTION_BELOW = 70
DIRECTIONS = ('higher', 'lower', 'neutral')
REVIEW_STATUSES = ('missing source', 'needs evidence', 'reviewable with caution', 'reviewable')
SIGNAL_STATUSES = ('indeterminate', 'improving', 'declining', 'unchanged', 'descriptive')
MISSING_SOURCE_NAMES = ('', 'Unspecified source')
TRACE_PATH = ('entity', 'indicator', 'period', 'measurement', 'source', 'confidence', 'review')
