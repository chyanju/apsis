"""AutoGen 0.2 (``pyautogen``) builders: a ``GroupChatManager``'s group chat and a nested-chat controller."""
from __future__ import annotations

from .agentutil import (
    _AGENT_NAME_RE,
    _agent_role,
    _function_map_keys,
    _human_input,
    _llm_declared_functions,
    _oid,
    _reply_chain,
    _safe_name,
    _tn,
    _wrap,
)


def _find_groupchat_v02(manager):
    """The manager's ``GroupChat``: ``.groupchat`` where defined, else a registered reply func's config."""
    gc = getattr(manager, "groupchat", None) or getattr(manager, "_groupchat", None)
    if gc is not None and hasattr(gc, "agents"):
        return gc
    for d in getattr(manager, "_reply_func_list", []) or []:
        cfg = d.get("config") if isinstance(d, dict) else None
        if cfg is not None and hasattr(cfg, "agents") and hasattr(cfg, "messages"):
            return cfg
    return None


def _extract_v02_groupchat(manager, gc, provenance) -> dict:
    nodes, edges, channels = [], [], []
    agents = list(getattr(gc, "agents", []) or [])
    name_to_id = {}

    for a in agents:
        nm = _safe_name(a, _tn(a))
        node_id = nm
        name_to_id[nm] = node_id
        attrs: dict[str, str] = {}
        hi = _human_input(a)
        if hi:
            attrs["human_input_mode"] = hi
        term = getattr(a, "_is_termination_msg", None) or getattr(a, "is_termination_msg", None)
        if callable(term):
            attrs["is_termination_msg"] = "declared"
        chain = _reply_chain(a)
        if chain:
            attrs["reply_func_chain"] = ",".join(chain)
            attrs["termination_reply_wired"] = str(
                any("check_termination_and_human_reply" in c for c in chain)
            )
        declared = _llm_declared_functions(a)
        if declared:
            attrs["declared_functions"] = ",".join(sorted(set(declared)))
        fmap = _function_map_keys(a)
        if fmap:
            attrs["function_map"] = ",".join(fmap)
        if not _AGENT_NAME_RE.match(nm):
            attrs["name_charset_valid"] = "false"

        nodes.append(
            {
                "id": node_id,
                "type_name": _tn(a),
                "kind": "agent",
                "name": nm,
                "role": _agent_role(a, is_manager=False),
                "instance_id": _oid(a),
                "attrs": attrs,
            }
        )

    mgr_name = _safe_name(manager, "manager")
    mgr_attrs: dict[str, str] = {}
    mgr_cfg = getattr(manager, "llm_config", None)
    if isinstance(mgr_cfg, dict):
        if mgr_cfg.get("functions"):
            mgr_attrs["llm_config_declares_functions"] = "true"
        if mgr_cfg.get("tools"):
            mgr_attrs["llm_config_declares_tools"] = "true"
        if mgr_cfg.get("functions") or mgr_cfg.get("tools"):
            mgr_attrs["declares_tools"] = "true"
    sel = getattr(gc, "speaker_selection_method", None)
    if sel is not None and not isinstance(sel, str):
        mgr_attrs["speaker_selection_method"] = "custom"
    elif isinstance(sel, str):
        mgr_attrs["speaker_selection_method"] = sel
    mr = getattr(gc, "max_round", None)
    if mr is not None:
        mgr_attrs["max_round"] = str(mr)
    arf = getattr(gc, "allow_repeat_speaker", None)
    if arf is not None:
        mgr_attrs["allow_repeat_speaker"] = str(arf)
    mgr_term = getattr(manager, "_is_termination_msg", None)
    if callable(mgr_term):
        mgr_attrs["is_termination_msg"] = "declared"

    transitions = _speaker_transitions_v02(gc, [n["name"] for n in nodes])
    if transitions is not None:
        mgr_attrs["speaker_transitions"] = "restricted"

    nodes.append(
        {
            "id": mgr_name,
            "type_name": _tn(manager),
            "kind": "router",
            "name": mgr_name,
            "role": "manager",
            "instance_id": _oid(manager),
            "declared_targets": [a["name"] for a in nodes],
            "attrs": mgr_attrs,
        }
    )

    if transitions is not None:
        for src_name, targets in transitions.items():
            for n in nodes:
                if n["name"] == src_name:
                    n["declared_targets"] = list(targets)
            for tgt in targets:
                edges.append(
                    {
                        "from": {"node": name_to_id.get(src_name, src_name), "socket": ""},
                        "to": {"node": name_to_id.get(tgt, tgt), "socket": ""},
                        "kind": "handoff",
                    }
                )

    tool_nodes, tool_edges = _tool_nodes_edges_v02(agents, name_to_id)
    nodes.extend(tool_nodes)
    edges.extend(tool_edges)

    member_ids = [a["name"] if isinstance(a, dict) else a for a in [n["name"] for n in nodes if n.get("kind") == "agent"]]
    channels.append(
        {
            "name": "messages",
            "type_repr": "list[dict]",
            "reducer": "append",
            "writers": member_ids + [mgr_name],
            "readers": member_ids + [mgr_name],
        }
    )

    return _wrap(nodes, edges, channels, provenance, start_nodes=[], output_nodes=[])


def _speaker_transitions_v02(gc, members: list[str]) -> dict[str, list[str]] | None:
    """Source name -> allowed next-speaker names, or None when the chat does not restrict transitions."""
    declared = getattr(gc, "allowed_or_disallowed_speaker_transitions", None)
    if not isinstance(declared, dict):
        return None

    def names(mapping) -> dict[str, list[str]]:
        return {_safe_name(src, str(src)): [_safe_name(t, str(t)) for t in (tgts or [])] for src, tgts in mapping.items()}

    resolved = getattr(gc, "allowed_speaker_transitions_dict", None)
    if isinstance(resolved, dict):
        return names(resolved)
    # releases without the resolved dict keep only the declaration, allowed or disallowed
    out = names(declared)
    if getattr(gc, "speaker_transitions_type", None) == "disallowed":
        return {m: [t for t in members if t not in out.get(m, [])] for m in members}
    return out


def _tool_nodes_edges_v02(agents, name_to_id):
    """A tool node per declared or registered function, with propose (caller) and execute (executor) edges."""
    nodes, edges = [], []
    callers: dict[str, list] = {}
    executors: dict[str, list] = {}
    for a in agents:
        an = _safe_name(a, _tn(a))
        for fn in _llm_declared_functions(a):
            callers.setdefault(fn, []).append(an)
        for fn in _function_map_keys(a):
            executors.setdefault(fn, []).append(an)
    all_tools = sorted(set(callers) | set(executors))
    for tool in all_tools:
        tid = f"tool:{tool}"
        nodes.append(
            {
                "id": tid,
                "type_name": "function",
                "kind": "tool",
                "name": tool,
                "attrs": {
                    "callers": ",".join(sorted(set(callers.get(tool, [])))),
                    "executors": ",".join(sorted(set(executors.get(tool, [])))),
                    "has_executor": "true" if executors.get(tool) else "false",
                },
            }
        )
        for c in callers.get(tool, []):
            edges.append(
                {"from": {"node": name_to_id.get(c, c), "socket": ""},
                 "to": {"node": tid, "socket": ""}, "kind": "tool", "branch": "propose"}
            )
        for e in executors.get(tool, []):
            edges.append(
                {"from": {"node": name_to_id.get(e, e), "socket": ""},
                 "to": {"node": tid, "socket": ""}, "kind": "tool", "branch": "execute"}
            )
    return nodes, edges


def _extract_v02_nested(agent, provenance) -> dict:
    nodes, edges, channels = [], [], []
    nm = _safe_name(agent, _tn(agent))
    name_to_id = {nm: nm}
    nodes.append(
        {
            "id": nm, "type_name": _tn(agent), "kind": "agent", "name": nm,
            "role": _agent_role(agent, False), "instance_id": _oid(agent), "attrs": {},
        }
    )
    registry = _nested_chat_registry(agent)
    declared_triggers: list[str] = []
    for trigger, queue in registry:
        trig_name = _trigger_name(trigger)
        declared_triggers.append(trig_name)
        for chat in queue or []:
            recip = chat.get("recipient") if isinstance(chat, dict) else None
            if recip is None:
                continue
            rnm = _safe_name(recip, _tn(recip))
            if rnm not in name_to_id:
                name_to_id[rnm] = rnm
                nodes.append(
                    {"id": rnm, "type_name": _tn(recip), "kind": "agent", "name": rnm,
                     "instance_id": _oid(recip),
                     "attrs": {"summary_method": str(chat.get("summary_method"))} if isinstance(chat, dict) else {}}
                )
            edges.append(
                {"from": {"node": trig_name, "socket": ""}, "to": {"node": nm, "socket": ""},
                 "kind": "control", "branch": "nested-chat-trigger", "condition": trig_name}
            )
            edges.append(
                {"from": {"node": nm, "socket": ""}, "to": {"node": rnm, "socket": ""},
                 "kind": "subflow", "branch": "nested-chat"}
            )
    # the trigger names are the controller's routing targets
    nodes[0]["declared_targets"] = sorted(set(declared_triggers))
    nodes[0]["attrs"]["nested_chat_triggers"] = ",".join(sorted(set(declared_triggers)))
    channels.append(
        {"name": "messages", "type_repr": "list[dict]", "reducer": "append",
         "writers": [n["name"] for n in nodes], "readers": [n["name"] for n in nodes]}
    )
    return _wrap(nodes, edges, channels, provenance, start_nodes=[nm], output_nodes=[])


def _nested_chat_registry(agent):
    """``[(trigger, chat_queue)]`` of ``register_nested_chats``; the queue sits in the reply func's closure."""
    out = []
    for d in getattr(agent, "_reply_func_list", []) or []:
        if not isinstance(d, dict):
            continue
        rf = d.get("reply_func")
        cfg = d.get("config")
        # some versions keep the queue in the config
        if isinstance(cfg, list) and cfg and isinstance(cfg[0], dict) and "recipient" in cfg[0]:
            out.append((d.get("trigger"), cfg))
            continue
        if getattr(rf, "__name__", "") == "_summary_from_nested_chats":
            queue = _closure_value(rf, "chat_queue")
            out.append((d.get("trigger"), queue))
    nested = getattr(agent, "_nested_chats", None)
    if isinstance(nested, list):
        for item in nested:
            if isinstance(item, dict):
                out.append((item.get("trigger"), item.get("chat_queue") or item.get("queue")))
    return out


def _closure_value(func, freevar_name):
    code = getattr(func, "__code__", None)
    clo = getattr(func, "__closure__", None)
    if not code or not clo:
        return None
    try:
        idx = code.co_freevars.index(freevar_name)
    except ValueError:
        return None
    try:
        return clo[idx].cell_contents
    except Exception:
        return None


def _trigger_name(trigger) -> str:
    if trigger is None:
        return "*"
    if isinstance(trigger, str):
        return trigger
    if isinstance(trigger, (list, tuple)):
        return ",".join(_trigger_name(t) for t in trigger)
    nm = getattr(trigger, "name", None)
    if isinstance(nm, str):
        return nm
    if isinstance(trigger, type):
        return trigger.__name__
    return str(trigger)
