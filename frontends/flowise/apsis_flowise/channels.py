"""Flowise flow-state channels (AgentFlow V2 / Sequential Agents): one IR channel per state key."""
from __future__ import annotations

import re

from .refs import _iter_strings

_STATE_READ = re.compile(r"\$flow\.state\.([A-Za-z_]\w*)")

# input keys whose value is a list of {key, value} state writes.
_STATE_WRITE_KEYS = (
    "startState", "agentUpdateState", "llmUpdateState", "toolUpdateState",
    "executeFlowUpdateState", "seqExecuteFlowUpdateState", "conditionUpdateState",
    "humanInputUpdateState", "iterationUpdateState",
)


def _state_channels(nodes_raw: list[dict]) -> list[dict]:
    """Writers set a key in a ``*State`` input (``startState`` seeds); readers reference ``$flow.state.KEY``."""
    writers: dict[str, list[str]] = {}
    readers: dict[str, list[str]] = {}
    types: dict[str, str] = {}

    for n in nodes_raw:
        nid = n.get("id")
        data = n.get("data", {})
        inputs = data.get("inputs") or {}
        for k, v in inputs.items():
            if k in _STATE_WRITE_KEYS and isinstance(v, list):
                for upd in v:
                    if isinstance(upd, dict) and upd.get("key"):
                        key = upd["key"]
                        writers.setdefault(key, [])
                        if nid not in writers[key]:
                            writers[key].append(nid)
        for s in _iter_strings(inputs):
            for key in _STATE_READ.findall(s):
                readers.setdefault(key, [])
                if nid not in readers[key]:
                    readers[key].append(nid)

    channels = []
    for name in sorted(set(writers) | set(readers)):
        # `messages` is append-only history; other keys overwrite.
        reducer = "append" if name == "messages" else "last-value"
        channels.append(
            {
                "name": name,
                "type_repr": types.get(name, "Any"),
                "reducer": reducer,
                "writers": writers.get(name, []),
                "readers": readers.get(name, []),
            }
        )
    return channels
