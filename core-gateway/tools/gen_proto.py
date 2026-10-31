"""Generate python code for the common protos and build the descriptor registry the gateway uses.

  common/proto                -> common/generated/python
  common/proto + <skill-repo>/skills/*/proto -> registry/descriptors.pb   (FileDescriptorSet with imports)

The skill-repo generates its own stubs (skill-repo: `make proto`); the gateway only needs the descriptors.
Skill-repo location: $SKILL_REPO (default ../skill-repo).
Run: python tools/gen_proto.py            (common code + registry)
     python tools/gen_proto.py --registry (registry only)"""
import os
import sys
from pathlib import Path

from grpc_tools import protoc

ROOT = Path(__file__).resolve().parent.parent
SKILL_REPO = Path(os.getenv("SKILL_REPO", ROOT.parent / "skill-repo")).resolve()


def _protoc(args: list[str]) -> None:
    if protoc.main(["protoc", *args]) != 0:
        raise SystemExit("protoc failed")


def generate_common() -> list[Path]:
    proto_root = ROOT / "common" / "proto"
    out = ROOT / "common" / "generated" / "python"
    files = sorted(proto_root.rglob("*.proto"))
    out.mkdir(parents=True, exist_ok=True)
    _protoc([f"-I{proto_root}", f"--python_out={out}", f"--grpc_python_out={out}", *map(str, files)])
    return files


def build_registry(skill_repo: Path = SKILL_REPO, out: Path | None = None) -> int:
    """One descriptor set from the common protos plus every skill proto found in the skill-repo."""
    common_root = ROOT / "common" / "proto"
    roots, files = [common_root], sorted(common_root.rglob("*.proto"))
    skills_dir = skill_repo / "skills"
    if not skills_dir.is_dir():
        raise SystemExit(f"skill-repo not found at {skill_repo} (set SKILL_REPO)")
    for skill in sorted(p for p in skills_dir.iterdir() if (p / "proto").is_dir()):
        roots.append(skill / "proto")
        files += sorted((skill / "proto").rglob("*.proto"))
    out = out or ROOT / "registry" / "descriptors.pb"
    out.parent.mkdir(parents=True, exist_ok=True)
    _protoc([*(f"-I{r}" for r in roots), "--include_imports", f"--descriptor_set_out={out}", *map(str, files)])
    return len(files)


def main() -> None:
    if "--registry" not in sys.argv:
        print(f"generated common: {len(generate_common())} proto files")
    n = build_registry()
    print(f"descriptor registry: {n} proto files -> registry/descriptors.pb (skills from {SKILL_REPO / 'skills'})")


if __name__ == "__main__":
    main()
