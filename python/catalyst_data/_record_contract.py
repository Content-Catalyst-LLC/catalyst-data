"""Generated from contracts/record_contract.json. Do not edit by hand."""

RECORD_CONTRACT = 'catalyst-data-record/1.0'
RECORD_SCHEMA_URI = 'https://sustainablecatalyst.com/schemas/catalyst-data-record-1.0.json'
RECORD_TYPES = ('measurement',)
ENTITY_TYPES = ('country', 'organization', 'project', 'program', 'site', 'policy', 'persona', 'experiment', 'dataset', 'other')
SOURCE_TYPES = ('internal record', 'third-party dataset', 'survey', 'public registry', 'model estimate', 'publication', 'sensor', 'api', 'other', 'unspecified')
PRODUCER_COMPONENTS = ('python-engine', 'browser-demo', 'migration-tool', 'external')
QUALITY_FLAGS = ('estimated', 'incomplete', 'outlier', 'imputed', 'stale', 'conflicting', 'restricted', 'unverified')
ID_PATTERN = '^[a-z][a-z0-9._:-]{2,255}$'
EXTENSION_KEY_PATTERN = '^[a-z][a-z0-9]*(?:[.-][a-z0-9-]+)+$'
SOURCE_CHECKSUM_PATTERN = '^sha256:[0-9a-f]{64}$'
LEGACY_CONTRACTS = ('catalyst-data-export/1.0', 'catalyst-data-export/1.0.1', 'unversioned-v1.0.x')
