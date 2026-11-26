"""Read a Flowise flow.json export."""
from __future__ import annotations

import json
import os


def get_flow(spec: str) -> tuple[dict, dict]:
    """``(flow_dict, provenance)`` for the path of a Flowise flow.json export."""
    if not os.path.exists(spec):
        raise FileNotFoundError(f"flow file not found: {spec}")
    with open(spec) as f:
        flow = json.load(f)
    if not isinstance(flow, dict) or not isinstance(flow.get("nodes"), list):
        raise ValueError(
            f"{spec!r} is not a Flowise flow export (expected a top-level object with a 'nodes' list)"
        )
    if not flow["nodes"]:
        raise ValueError(f"{spec!r} is a flow without nodes")
    return flow, {"kind": "flow-json", "path": spec, "extractor": "flowise"}
