"""Introspect a built AutoGen orchestration into the IR base facts, dispatching on the entry object's shape to
the builders in ``v02`` (pyautogen) and ``v04`` (autogen-agentchat, autogen-core)."""
from __future__ import annotations

from .agentutil import _oid, _reply_chain, _safe_name, _tn, _wrap
from .v02 import _extract_v02_groupchat, _extract_v02_nested, _find_groupchat_v02
from .v04 import _extract_v04_pubsub, _extract_v04_team


def _looks_like_team_v04(obj) -> bool:
    tn = type(obj).__name__
    if tn in ("Swarm", "MagenticOneGroupChat", "RoundRobinGroupChat", "SelectorGroupChat", "GraphFlow"):
        return True
    mro = [c.__name__ for c in type(obj).__mro__]
    return any(b in mro for b in ("BaseGroupChat", "GraphFlow"))


def _looks_like_runtime(obj) -> bool:
    return "AgentRuntime" in [c.__name__ for c in type(obj).__mro__]


def _looks_like_manager_v02(obj) -> bool:
    return "GroupChatManager" in [c.__name__ for c in type(obj).__mro__]


def _looks_like_conversable_v02(obj) -> bool:
    return "ConversableAgent" in [c.__name__ for c in type(obj).__mro__]


def _looks_like_agent(obj) -> bool:
    return any(c.__name__.endswith("Agent") for c in type(obj).__mro__)


def extract(workflow, provenance: dict) -> dict:
    if isinstance(workflow, (list, tuple)):
        workflows = []
        for i, item in enumerate(workflow):
            ir = extract(item, provenance)
            ir["id"] = f"graph{i}"
            workflows.append(ir)
        return {"workflows": workflows}

    if _looks_like_runtime(workflow):
        return _extract_v04_pubsub(workflow, provenance)

    if _looks_like_team_v04(workflow):
        return _extract_v04_team(workflow, provenance)

    if _looks_like_manager_v02(workflow):
        gc = _find_groupchat_v02(workflow)
        if gc is not None:
            return _extract_v02_groupchat(workflow, gc, provenance)

    if _looks_like_conversable_v02(workflow):
        return _extract_v02_nested(workflow, provenance)

    if not _looks_like_agent(workflow):
        raise TypeError(
            f"expected an AutoGen group chat, team, runtime or agent, got "
            f"{type(workflow).__module__}.{type(workflow).__name__}"
        )
    nm = _safe_name(workflow, _tn(workflow))
    chain = _reply_chain(workflow)
    attrs = {}
    if chain:
        attrs["reply_func_chain"] = ",".join(chain)
        attrs["termination_reply_wired"] = str(any("check_termination" in c for c in chain))
    return _wrap(
        [{"id": nm, "type_name": _tn(workflow), "kind": "agent", "name": nm,
          "instance_id": _oid(workflow), "attrs": attrs}],
        [], [], provenance, start_nodes=[nm], output_nodes=[],
    )
