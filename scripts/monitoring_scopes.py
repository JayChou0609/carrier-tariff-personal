"""One scope contract for collection, archive guards and WeCom notifications."""
import json
from pathlib import Path
CONFIG = json.loads((Path(__file__).resolve().parents[1] / 'custom/monitoring-scopes.json').read_text(encoding='utf-8'))
REGIONS = CONFIG['regions']
TARGETS = {carrier: list(REGIONS) for carrier in CONFIG['carriers']}
