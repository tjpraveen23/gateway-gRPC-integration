"""pytest: put this repo, every skill's generated stubs and core-gateway's shared code on sys.path (like scripts/env.sh)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORE = Path(os.getenv("CORE_GATEWAY", ROOT.parent / "core-gateway")).resolve()

for p in [ROOT, CORE / "common" / "lib", CORE / "common" / "generated" / "python",
          *sorted((ROOT / "skills").glob("*/generated/python"))]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
