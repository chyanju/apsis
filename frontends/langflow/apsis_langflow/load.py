"""Read an exported langflow flow.json."""
from __future__ import annotations

import json


def load_flow(path: str) -> tuple[dict, dict]:
    """``(flow_dict, provenance)`` for the flow exported at ``path``."""
    with open(path) as f:
        flow = json.load(f)
    nodes = flow.get("data", {}).get("nodes") if isinstance(flow, dict) and isinstance(flow.get("data"), dict) else None
    if not isinstance(nodes, list):
        raise ValueError(f"{path!r} is not a langflow flow export (expected an object with a 'data.nodes' list)")
    if not nodes:
        raise ValueError(f"{path!r} is a flow without nodes")
    provenance = {"kind": "flow-json", "path": path, "extractor": "langflow"}
    return flow, provenance
