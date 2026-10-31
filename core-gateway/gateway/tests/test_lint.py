import shutil

import pytest

from crown_common import config
from tools.lint_skills import lint

if not config.SKILLS_DIR.is_dir():
    pytest.skip(f"skill-repo not found at {config.SKILLS_DIR} (set SKILLS_DIR / SKILL_REPO)", allow_module_level=True)


def test_skill_repo_layout_is_clean():
    assert lint(config.SKILLS_DIR, config.DESCRIPTOR_PATH) == []


def test_lint_reports_missing_pieces(tmp_path):
    skills = tmp_path / "skills"
    shutil.copytree(config.SKILLS_DIR, skills, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.rmtree(skills / "account" / "proto")
    (skills / "insights" / "skill.md").unlink()
    errors = lint(skills, config.DESCRIPTOR_PATH)
    assert any("account: missing proto" in e for e in errors) and any("insights: missing skill.md" in e for e in errors)


def test_lint_reports_missing_skill_repo(tmp_path):
    assert "not found" in lint(tmp_path / "nope", config.DESCRIPTOR_PATH)[0]
