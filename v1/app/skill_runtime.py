"""Skill loading, dependency planning and the generic step runner.

A skill = skills/<name>/skill.json (machine config + version_history) + skills/<name>/skill.md (instructions).
Each step in skill.json names a gRPC call ("Service.Method"), its input mapping, where to save the output,
and optional checks (retry / fail_if_empty). Inputs use ${path} references into the run context."""
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from google.protobuf import json_format

import crown_pb2 as pb
from common import ROOT


class ManualReview(Exception):
    """A skill cannot produce an automated result; the analyst must handle it manually."""


class SkillConfigError(Exception):
    """skill.json is invalid."""


# ------------------------------------------------------------------ loading
@dataclass
class Skill:
    name: str
    meta: dict
    md: str

    @property
    def version(self) -> str:
        return self.meta["version"]

    @property
    def requires(self) -> list[str]:
        return self.meta.get("requires", [])

    @property
    def required(self) -> bool:
        return self.meta.get("required", True)

    def catalog_entry(self) -> dict:
        """What the routing LLM sees about this skill."""
        return {"name": self.name, "description": self.meta["description"],
                "triggers": self.meta.get("triggers", []), "requires": self.requires}


def rpc_signature(call: str):
    """'Service.Method' -> (service, method, request message class)."""
    try:
        svc, meth = call.split(".")
        method = pb.DESCRIPTOR.services_by_name[svc].methods_by_name[meth]
    except (ValueError, KeyError) as e:
        raise SkillConfigError(f"unknown gRPC call '{call}'") from e
    return svc, meth, getattr(pb, method.input_type.name)


def _validate(dirname: str, meta: dict) -> None:
    for key in ("name", "version", "version_history", "description", "steps", "outputs"):
        if key not in meta:
            raise SkillConfigError(f"{dirname}/skill.json: missing '{key}'")
    if meta["name"] != dirname:
        raise SkillConfigError(f"{dirname}/skill.json: name '{meta['name']}' must match the folder name")
    hist = meta["version_history"]
    if not hist or hist[-1].get("version") != meta["version"]:
        raise SkillConfigError(f"{dirname}/skill.json: the last version_history entry must equal 'version'")
    ids = [s["id"] for s in meta["steps"]]
    if len(ids) != len(set(ids)):
        raise SkillConfigError(f"{dirname}/skill.json: duplicate step ids")
    for s in meta["steps"]:
        rpc_signature(s["call"])
        retry = s.get("check", {}).get("retry_from")
        if retry and retry not in ids:
            raise SkillConfigError(f"{dirname}/skill.json: retry_from '{retry}' is not a step id")


def load_skills(root: Path = ROOT / "skills") -> dict[str, Skill]:
    skills: dict[str, Skill] = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        jf, mf = d / "skill.json", d / "skill.md"
        if not jf.exists():
            continue
        meta = json.loads(jf.read_text(encoding="utf-8"))
        _validate(d.name, meta)
        skills[meta["name"]] = Skill(meta["name"], meta, mf.read_text(encoding="utf-8") if mf.exists() else "")
    for s in skills.values():
        for dep in s.requires:
            if dep not in skills:
                raise SkillConfigError(f"skill '{s.name}' requires unknown skill '{dep}'")
    return skills


# ------------------------------------------------------------------ planning
def plan_stages(chosen: list[str], skills: dict[str, Skill]) -> list[list[str]]:
    """Add required skills transitively, then group into stages. Skills in a stage run in parallel."""
    need: set[str] = set()
    stack = list(chosen)
    while stack:
        n = stack.pop()
        if n in need:
            continue
        need.add(n)
        stack.extend(skills[n].requires)
    stages, done = [], set()
    while len(done) < len(need):
        ready = sorted(n for n in need - done if set(skills[n].requires) <= done)
        if not ready:
            raise SkillConfigError("cyclic skill dependencies")
        stages.append(ready)
        done |= set(ready)
    return stages


def union_ms(calls: list[dict]) -> int:
    """Total wall time covered by the calls; overlapping (parallel) calls are counted once."""
    iv = sorted((c["start_ms"], c["start_ms"] + c["ms"]) for c in calls)
    total, cs, ce = 0, None, None
    for s, e in iv:
        if ce is None or s > ce:
            if ce is not None:
                total += ce - cs
            cs, ce = s, e
        else:
            ce = max(ce, e)
    if ce is not None:
        total += ce - cs
    return total


# ------------------------------------------------------------------ ${path} resolution
_VAR = re.compile(r"\$\{([\w.]+)\}")


def lookup(ctx, path: str):
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _text(v) -> str:
    if v is None:
        return ""
    return v if isinstance(v, str) else json.dumps(v)


def resolve(value, ctx):
    """A string that is exactly '${a.b}' keeps the value's type; other strings are interpolated."""
    if isinstance(value, str):
        m = _VAR.fullmatch(value)
        if m:
            v = lookup(ctx, m.group(1))
            return "" if v is None else v
        return _VAR.sub(lambda mm: _text(lookup(ctx, mm.group(1))), value)
    if isinstance(value, dict):
        return {k: resolve(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, ctx) for v in value]
    return value


def _is_repeated(f) -> bool:
    r = getattr(f, "is_repeated", None)
    return bool(r) if r is not None else f.label == f.LABEL_REPEATED


def build_request(cls, data: dict):
    fields = cls.DESCRIPTOR.fields_by_name
    clean = {}
    for k, v in data.items():
        f = fields.get(k)
        if f is None:
            raise SkillConfigError(f"{cls.DESCRIPTOR.name} has no field '{k}'")
        if f.type == f.TYPE_STRING and not _is_repeated(f) and not isinstance(v, str):
            v = json.dumps(v)                      # dict/list -> JSON string field
        if f.type in (f.TYPE_INT32, f.TYPE_INT64) and isinstance(v, str):
            v = int(v) if v else 0
        clean[k] = v
    return json_format.ParseDict(clean, cls())


def to_dict(msg) -> dict:
    d = json_format.MessageToDict(msg, preserving_proto_field_name=True)
    for f in msg.DESCRIPTOR.fields:
        if f.name not in d:
            d[f.name] = ([] if _is_repeated(f) else "" if f.type == f.TYPE_STRING
                         else False if f.type == f.TYPE_BOOL else 0)
    return d


# ------------------------------------------------------------------ step runner
# invoke(skill_name, step_id, service, method, request, timeout) -> response message
Invoke = Callable[[str, str, str, str, object, float], Awaitable[object]]


async def execute_skill(skill: Skill, ctx: dict, invoke: Invoke) -> dict:
    """Run the skill's steps in order and return its resolved outputs."""
    local = dict(ctx)
    local["skill_md"] = skill.md
    local["feedback"] = ""
    profiles = skill.meta.get("profiles")
    if profiles:
        name = skill.meta.get("profile_by_intent", {}).get(ctx.get("intent"), skill.meta.get("default_profile"))
        local["profile_name"] = name
        local["profile"] = profiles.get(name, {})

    steps = skill.meta["steps"]
    index = {s["id"]: i for i, s in enumerate(steps)}
    attempts: dict[str, int] = {}
    i = 0
    while i < len(steps):
        step = steps[i]
        svc, meth, req_cls = rpc_signature(step["call"])
        request = build_request(req_cls, resolve(step.get("input", {}), local))
        response = await invoke(skill.name, step["id"], svc, meth, request, step.get("timeout", 30))
        out = to_dict(response)
        if step.get("save_as"):
            local[step["save_as"]] = out

        check = step.get("check")
        if check and not lookup(out, check["field"]):
            attempts[step["id"]] = attempts.get(step["id"], 0) + 1
            if attempts[step["id"]] < check.get("max_attempts", 1) and check.get("retry_from"):
                local["feedback"] = resolve(check.get("feedback", ""), local)
                i = index[check["retry_from"]]
                continue
            raise ManualReview(resolve(check.get("on_fail", "Step check failed"), local))

        empty = step.get("fail_if_empty")
        if empty and not lookup(out, empty["field"]):
            raise ManualReview(empty["reason"])
        i += 1

    return resolve(skill.meta["outputs"], local)
