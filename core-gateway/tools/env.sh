# POSIX shell. Source from the core-gateway root:   . tools/env.sh
# PYTHONPATH: this repo, the common lib and the common generated code.
# The skill-repo is added too (if present) so the gateway tests and `make lint` can import the skill services.
ROOT="$(pwd)"
export SKILL_REPO="${SKILL_REPO:-$ROOT/../skill-repo}"
export PYTHONPATH="$ROOT:$ROOT/common/lib:$ROOT/common/generated/python"
