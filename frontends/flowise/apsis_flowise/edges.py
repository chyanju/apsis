"""Flowise edge handles -> IR socket refs, and the kind of each edge."""
from __future__ import annotations

import re


def _resolve_socket(handle: str, node_id: str, side: str) -> dict:
    """The ``{node, socket}`` of an edge end; a handle that is just the node id has socket ``""``."""
    socket = ""
    if handle and handle != node_id:
        rest = handle
        if rest.startswith(node_id + "-"):
            rest = rest[len(node_id) + 1:]
        # rest, e.g. "output-0", "input-model-BaseLanguageModel", "loopBackToNode-<target>"
        m = re.match(r"(?:input|output)-(\d+)$", rest)
        if m:
            socket = f"output-{m.group(1)}"
        else:
            m = re.match(r"(?:input|output)-([^-]+)", rest)
            if m:
                socket = m.group(1)
            elif rest:
                socket = rest
    return {"node": node_id, "socket": socket}


def _edge_kind(src_node: dict, tgt_socket: str, branch: str | None, kinds: dict) -> str:
    if branch is not None:
        return "conditional"
    skind = kinds.get(src_node, "component")
    if skind == "subflow":
        return "subflow"
    sock = (tgt_socket or "").lower()
    if sock in ("model", "language model") or sock.startswith("model"):
        return "model"
    if sock in ("tools", "tool") or skind == "tool":
        return "tool"
    return "data"
