"""Generate python stubs for every skill: skills/<s>/proto -> skills/<s>/generated/python.

Skill protos may import the common protos (e.g. insights imports crown/common/v1/sop_retrieval.proto), which live in
core-gateway. Core-gateway location: $CORE_GATEWAY (default ../core-gateway).
After changing a proto also run, in core-gateway:  make registry   (the gateway reads registry/descriptors.pb)
Run: python scripts/gen_proto.py"""
import os
from pathlib import Path

from grpc_tools import protoc

ROOT = Path(__file__).resolve().parent.parent
CORE = Path(os.getenv("CORE_GATEWAY", ROOT.parent / "core-gateway")).resolve()
COMMON_PROTO = CORE / "common" / "proto"


def main() -> None:
    if not COMMON_PROTO.is_dir():
        raise SystemExit(f"core-gateway not found at {CORE} (set CORE_GATEWAY)")
    for skill in sorted(p for p in (ROOT / "skills").iterdir() if (p / "proto").is_dir()):
        files = sorted((skill / "proto").rglob("*.proto"))
        out = skill / "generated" / "python"
        out.mkdir(parents=True, exist_ok=True)
        rc = protoc.main(["protoc", f"-I{skill / 'proto'}", f"-I{COMMON_PROTO}", f"--python_out={out}",
                          f"--grpc_python_out={out}", *map(str, files)])
        if rc != 0:
            raise SystemExit(f"protoc failed for {skill.name}")
        print(f"generated {skill.name}: {len(files)} proto file(s)")


if __name__ == "__main__":
    main()
