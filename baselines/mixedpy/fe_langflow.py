"""Langflow front-end: flow.json -> unified Graph."""
import json
from graph import Graph, Node, Edge

ENTRY_TYPES = {"ChatInput", "TextInput"}
TERMINAL_TYPES = {"ChatOutput", "TextOutput"}
LOOP_TYPES = {"Loop"}


def load(path):
    d = json.load(open(path, encoding="utf-8"))
    data = d.get("data", d)
    g = Graph("langflow")
    for n in data.get("nodes", []):
        nid = n["id"]
        nd = n.get("data", {})
        typ = nd.get("type", nid.split("-")[0])
        # not read: template.required also marks fields typed in by hand, not wired
        g.add_node(Node(
            id=nid, kind=typ, name=typ, required_inputs=set(),
            is_entry=typ in ENTRY_TYPES,
            is_terminal=typ in TERMINAL_TYPES,
            is_loop_control=("Loop" in typ),
        ))
    for e in data.get("edges", []):
        ed = e.get("data") or {}
        th = ed.get("targetHandle") or {}
        sh = ed.get("sourceHandle") or {}
        g.add_edge(Edge(
            src=e.get("source"), dst=e.get("target"),
            src_handle=sh.get("name", e.get("sourceHandle", "")),
            dst_handle=th.get("fieldName", e.get("targetHandle", "")),
        ))
    return g
