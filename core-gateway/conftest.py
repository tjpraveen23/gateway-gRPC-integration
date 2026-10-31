"""pytest: put this repo, the common lib and the common generated code on sys.path (like tools/env.sh).

Tests that need the skills (runtime, lint, end-to-end) use the sibling skill-repo ($SKILL_REPO, default ../skill-repo);
when it is missing they are skipped, and the common and registry tests still run."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
SKILL_REPO = Path(os.getenv("SKILL_REPO", ROOT.parent / "skill-repo")).resolve()
HAS_SKILLS = (SKILL_REPO / "skills").is_dir()

paths = [ROOT, ROOT / "common" / "lib", ROOT / "common" / "generated" / "python"]
for p in paths:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
if HAS_SKILLS:                      # appended, so this repo's modules always win
    os.environ.setdefault("SKILLS_DIR", str(SKILL_REPO / "skills"))
    for p in [SKILL_REPO, *sorted((SKILL_REPO / "skills").glob("*/generated/python"))]:
        if str(p) not in sys.path:
            sys.path.append(str(p))

needs_skills = pytest.mark.skipif(not HAS_SKILLS, reason=f"skill-repo not found at {SKILL_REPO} (set SKILL_REPO)")
