"""Lint the monorepo layout and every skill contract. Exit code 1 when there are problems.

Checks per skill folder (in the skill-repo): skill.json + skill.md, proto/, generated/python/, service/server.py;
skill.json validity (version_history, steps resolve in registry/descriptors.pb, prerequisites exist, no cycles); the
declared `service` exists in the registry.
Run: python tools/lint_skills.py [skills_dir]      (default: $SKILLS_DIR or ../skill-repo/skills)"""
import sys
from pathlib import Path

from crown_common import config
from gateway.app.descriptor_registry import DescriptorRegistry, UnknownMethod
from gateway.app.skill_runtime import SkillConfigError, load_skills, plan_stages

ROOT = Path(__file__).resolve().parent.parent


def lint(skills_dir: Path | None = None, registry_path: Path | None = None) -> list[str]:
    errors: list[str] = []
    skills_dir = Path(skills_dir or config.SKILLS_DIR)
    registry_path = Path(registry_path or config.DESCRIPTOR_PATH)
    if not skills_dir.is_dir():
        return [f"skills directory not found: {skills_dir}"]
    for d in sorted(p for p in skills_dir.iterdir() if p.is_dir() and p.name != "__pycache__"):
        for rel in ("skill.json", "skill.md", "proto", "generated/python", "service/server.py"):
            if not (d / rel).exists():
                errors.append(f"{d.name}: missing {rel}")
        if not list((d / "proto").rglob("*.proto")) if (d / "proto").exists() else True:
            errors.append(f"{d.name}: no .proto file under proto/")
    try:
        registry = DescriptorRegistry(registry_path)
        skills = load_skills(skills_dir, registry)
        plan_stages(list(skills), skills)
        for s in skills.values():
            svc = s.meta.get("service")
            if svc:
                try:
                    registry.pool.FindServiceByName(svc)
                except KeyError:
                    errors.append(f"{s.name}: declared service '{svc}' is not in the registry")
    except (SkillConfigError, UnknownMethod, OSError) as e:
        errors.append(str(e))
    return errors


if __name__ == "__main__":
    problems = lint(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    for p in problems:
        print("ERROR:", p)
    print("lint ok" if not problems else f"{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
