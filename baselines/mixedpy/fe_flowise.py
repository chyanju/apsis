"""Flowise front-end: flow.json -> unified Graph. Schema-aware (knows Flowise's component format)."""
import json, re
from graph import Graph, Node, Edge

TERMINAL_NAMES = {"chatOutput", "end", "endAgentflow", "directReply", "directReplyAgentflow"}
ENTRY_NAMES = {"chatInput", "start", "startAgentflow", "stickyNote"}
LOOP_NAMES = {"seqLoop", "loopAgentflow"}
# anchors Flowise defines as optional (flow.json does not flag these)
OPTIONAL_ANCHORS = {"cache", "memory", "moderations", "inputModeration", "recordManager",
                    "outputParser", "chatHistory", "vectorStoreRetriever", "credential"}
TEMPLATE_RE = re.compile(r"\{\{([A-Za-z0-9_]+)\.data\.instance\}\}")


def _input_name(handle):
    parts = (handle or "").split("-")
    if "input" in parts:
        i = parts.index("input")
        if i + 1 < len(parts):
            return parts[i + 1]
    return handle or ""


def load(path):
    d = json.load(open(path, encoding="utf-8"))
    g = Graph("flowise")
    for n in d.get("nodes", []):
        nid = n["id"]
        nd = n.get("data", {})
        name = nd.get("name", "")
        typ = nd.get("type", "")
        anchors = nd.get("inputAnchors", [])
        req = {a.get("name") for a in anchors
               if a.get("optional") is not True and a.get("list") is not True
               and a.get("name") not in OPTIONAL_ANCHORS}
        tmpl = {}
        for k, v in (nd.get("inputs") or {}).items():
            ids = set(TEMPLATE_RE.findall(v if isinstance(v, str) else json.dumps(v)))
            if ids:
                tmpl[k] = ids
        has_out = bool(nd.get("outputAnchors"))
        g.add_node(Node(
            id=nid, kind=nd.get("category", ""), name=name,
            required_inputs=req, template_inputs=tmpl,
            is_entry=name in ENTRY_NAMES,
            is_terminal=(name in TERMINAL_NAMES) or (not has_out),
            is_loop_control=(name in LOOP_NAMES) or ("oop" in typ),
        ))
    for e in d.get("edges", []):
        g.add_edge(Edge(
            src=e.get("source"), dst=e.get("target"),
            src_handle=e.get("sourceHandle", ""),
            dst_handle=_input_name(e.get("targetHandle", "")),
        ))
    return g
