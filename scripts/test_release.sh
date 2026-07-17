#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export PYTHONPATH="$ROOT/python${PYTHONPATH:+:$PYTHONPATH}"

find python scripts tests -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf .pytest_cache .release-check-pycache
for test_file in tests/test_*.py; do
  python3 -m pytest -q -o addopts='' "$test_file"
done

if command -v node >/dev/null 2>&1; then
  node --check wordpress/catalyst-data-demo/assets/catalyst-data-contract.js
  node --check wordpress/catalyst-data-demo/assets/catalyst-data-record-contract.js
  node --check wordpress/catalyst-data-demo/assets/catalyst-data-demo.js
  node --check wordpress/catalyst-data-demo/assets/catalyst-data-embed.js
  node scripts/test_browser_contract.js
else
  echo "SKIP: node is not installed"
fi

if command -v php >/dev/null 2>&1; then
  php -l wordpress/catalyst-data-demo/catalyst-data-demo.php
else
  echo "SKIP: php is not installed"
fi

echo "Catalyst Data full release suite passed."
