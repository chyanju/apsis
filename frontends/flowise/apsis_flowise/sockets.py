"""Flowise input/output handles -> IR sockets."""
from __future__ import annotations

import re

from .types import _canon_type


def _input_sockets(data: dict) -> list[dict]:
    """Input sockets from ``inputAnchors`` (connections) and ``inputParams`` (config values)."""
    inputs_map = data.get("inputs") or {}
    seen: set[str] = set()
    out: list[dict] = []

    def add(spec: dict, is_anchor: bool):
        name = spec.get("name")
        if not name or name in seen:
            return
        seen.add(name)
        has_value = name in inputs_map and inputs_map.get(name) not in (None, "", [], {})
        # Flowise treats these bindings as optional on any component.
        optional = bool(spec.get("optional", False)) or name in (
            "cache", "memory", "moderation", "inputModeration", "tools",
        )
        # A Sequential Agents node takes its chat model from seqStart.
        inherited = name == "model" and str(data.get("name", "")).startswith("seq")
        mandatory = is_anchor and not optional and not has_value and not inherited
        out.append(
            {
                "name": name,
                "type_repr": _canon_type(spec.get("type")),
                "has_default": has_value or optional or spec.get("default") is not None,
                "variadic": str(spec.get("type", "")).endswith("array")
                or isinstance(inputs_map.get(name), list),
                "mandatory": bool(mandatory),
                # only an edge can feed an anchor
                "connection_only": is_anchor,
            }
        )

    for a in data.get("inputAnchors") or []:
        add(a, is_anchor=True)
    for p in data.get("inputParams") or []:
        add(p, is_anchor=False)
    return out


def _flatten_output_anchors(data: dict) -> list[dict]:
    """Flat output specs: plain anchors, the ``options`` of an option group, and AgentFlow branch anchors."""
    specs: list[dict] = []
    for oa in data.get("outputAnchors") or []:
        if isinstance(oa.get("options"), list):
            for opt in oa["options"]:
                specs.append({"name": opt.get("name"), "type": opt.get("type"), "branch": False,
                              "id": opt.get("id")})
            continue
        anchor_id = oa.get("id", "")
        # AgentFlow branch anchor: id ends in `-output-<n>` with no type.
        m = re.search(r"-output-(\d+)$", anchor_id)
        is_branch = m is not None or (oa.get("type") in (None, "") and oa.get("name") == data.get("name"))
        specs.append({"name": oa.get("name"), "type": oa.get("type"),
                      "branch": is_branch, "id": anchor_id, "branch_idx": m.group(1) if m else None})
    return specs


def _output_sockets(data: dict, kind: str) -> list[dict]:
    specs = _flatten_output_anchors(data)
    out: list[dict] = []
    seen: set[str] = set()
    branch_count = sum(1 for s in specs if s.get("branch"))
    for s in specs:
        # AgentFlow branch anchors all share the node name
        name = s["name"]
        if s.get("branch") and s.get("branch_idx") is not None:
            name = f"output-{s['branch_idx']}"
        if not name or name in seen:
            continue
        seen.add(name)
        # A router/condition branch output, or any output of a may-stop node, may be omitted on a run.
        may_emit = bool(s.get("branch")) and branch_count > 1 or kind in ("router", "human-input")
        out.append({"name": name, "type_repr": _canon_type(s.get("type")), "may_emit": may_emit})
    return out
