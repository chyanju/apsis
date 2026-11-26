"""IR edges (tool, conditional, subflow or data) and the start/output nodes of a langflow flow."""
from __future__ import annotations

from .nodekind import _BRANCH_OUTPUTS
from .typecanon import _as_list


def _branch_label(out_name: str, kind: str) -> str | None:
    if out_name in _BRANCH_OUTPUTS:
        return out_name
    return None


def _build_edges(raw_edges: list, node_kinds: dict[str, str]) -> list[dict]:
    edges = []
    for e in raw_edges:
        if not isinstance(e, dict):
            continue
        src = e.get("source", "")
        tgt = e.get("target", "")
        data = e.get("data", {}) or {}
        sh = data.get("sourceHandle", {}) or {}
        th = data.get("targetHandle", {}) or {}

        src_sock = sh.get("name") or e.get("sourceHandle") or ""
        # a loopback edge's targetHandle has no fieldName
        tgt_sock = th.get("fieldName") or e.get("targetHandle") or ""

        out_types = _as_list(sh.get("output_types"))

        kind = "data"
        branch = None
        tgt_kind = node_kinds.get(tgt, "component")
        src_kind = node_kinds.get(src, "component")

        if "Tool" in out_types or src_sock == "component_as_tool":
            kind = "tool"
        elif src_kind == "router":
            label = _branch_label(src_sock, src_kind)
            if label is not None:
                kind = "conditional"
                branch = label
        if tgt_kind == "subflow" or "~" in tgt_sock:
            # into a sub-flow node, or onto an exposed inner input ("~")
            kind = "subflow"

        edge = {
            "from": {"node": src, "socket": src_sock},
            "to": {"node": tgt, "socket": tgt_sock},
            "kind": kind,
        }
        if branch is not None:
            edge["branch"] = branch
        edges.append(edge)
    return edges


def _start_output_nodes(nodes: list[dict]) -> tuple[list[str], list[str]]:
    """Start and output nodes by component class (ChatInput, ChatOutput, ...)."""
    starts, outs = [], []
    for n in nodes:
        t = (n.get("type_name") or "").lower()
        if t in ("chatinput", "textinput") or t.endswith("input") and "chat" in t:
            starts.append(n["id"])
        elif t in ("chatoutput", "textoutput") or (t.endswith("output") and "chat" in t):
            outs.append(n["id"])
    return starts, outs
