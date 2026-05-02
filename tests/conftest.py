from __future__ import annotations

import sys
from pathlib import Path

# Make `custom_components.axuus` importable as a regular package without
# pulling in Home Assistant. The api/ subpackage has no HA dependencies.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
