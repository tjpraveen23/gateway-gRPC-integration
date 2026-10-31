# POSIX shell. Source from the skill-repo root:   . scripts/env.sh
# PYTHONPATH: this repo (python package `skills`), every skill's generated stubs, and the shared code that lives in
# core-gateway (crown_common lib + generated common stubs). Core-gateway location: $CORE_GATEWAY (default ../core-gateway).
ROOT="$(pwd)"
export CORE_GATEWAY="${CORE_GATEWAY:-$ROOT/../core-gateway}"
if [ ! -d "$CORE_GATEWAY/common/lib" ]; then echo "core-gateway not found at $CORE_GATEWAY (set CORE_GATEWAY)" >&2; fi
export PYTHONPATH="$ROOT:$CORE_GATEWAY/common/lib:$CORE_GATEWAY/common/generated/python"
for d in "$ROOT"/skills/*/generated/python; do export PYTHONPATH="$PYTHONPATH:$d"; done
