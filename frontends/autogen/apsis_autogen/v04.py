"""AutoGen 0.4+ builders: ``BaseGroupChat`` teams, ``GraphFlow``, and autogen-core pub/sub runtimes."""
from __future__ import annotations

import inspect

from .agentutil import (
    _agent_node_v04,
    _agent_publishes,
    _bool_attr,
    _oid,
    _safe_name,
    _termination_repr,
    _tn,
    _wrap,
    _message_sockets,
    _produced_message_classes,
    _thread_guarded_message_classes,
)


def _team_participants(team):
    for attr in ("_participants", "participants", "_agents"):
        v = getattr(team, attr, None)
        if isinstance(v, (list, tuple)) and v:
            return list(v)
    return []


def _extract_v04_team(team, provenance, team_index: int = 0) -> dict:
    nodes, edges, channels = [], [], []
    participants = _team_participants(team)
    part_names = []
    for a in participants:
        node = _agent_node_v04(a)
        # its ChatAgentContainer hands the participant every message the team relays, unfiltered
        node["attrs"]["takes_all_messages"] = "true"
        nodes.append(node)
        part_names.append(node["name"])

    team_tn = type(team).__name__
    is_swarm = "Swarm" in team_tn
    is_graphflow = "GraphFlow" in team_tn

    mgr_id = f"__team__{team_index}" if team_index else "__team__"
    mgr_attrs: dict[str, str] = {"team_type": team_tn}
    term = _termination_repr(getattr(team, "_termination_condition", None) or getattr(team, "termination_condition", None))
    if term:
        mgr_attrs["termination_condition"] = term
    arf = _bool_attr(team, "_allow_repeated_speaker", "allow_repeated_speaker")
    if arf is not None:
        mgr_attrs["allow_repeated_speaker"] = str(arf)
    msa = getattr(team, "_max_selector_attempts", None)
    if msa is None:
        msa = getattr(team, "max_selector_attempts", None)
    if msa is not None:
        mgr_attrs["max_selector_attempts"] = str(msa)
    relayed, supertypes = _message_sockets([t for a in participants for t in _produced_message_classes(a)], inputs=False)
    mgr_attrs.update(supertypes)
    # handle_agent_response appends every participant response to the manager's thread
    mgr_attrs["takes_all_messages"] = "true"
    taken, _ = _message_sockets(_manager_accepted_classes(team), inputs=True)
    nodes.append(
        {"id": mgr_id, "type_name": _tn(team), "kind": "router", "name": mgr_id,
         "role": "manager", "declared_targets": list(part_names), "instance_id": _oid(team),
         "inputs": taken, "outputs": relayed, "attrs": mgr_attrs}
    )

    if is_graphflow:
        edges.extend(_graphflow_edges(team, {n["name"]: n["id"] for n in nodes}))
        _annotate_graphflow_joins(team, nodes)
    elif is_swarm:
        name_to_id = {n["name"]: n["id"] for n in nodes}
        for n in nodes:
            for tgt in n.get("declared_targets", []) or []:
                edges.append(
                    {"from": {"node": n["id"], "socket": ""},
                     "to": {"node": name_to_id.get(tgt, tgt), "socket": ""}, "kind": "handoff"}
                )
    else:
        # round-robin, selector, magentic: the manager may select any participant
        for n in nodes:
            if n["id"] == mgr_id:
                continue
            edges.append(
                {"from": {"node": mgr_id, "socket": ""}, "to": {"node": n["id"], "socket": ""},
                 "kind": "control", "branch": "speaker-select"}
            )

    channels.append(
        {"name": "messages", "type_repr": "list[ChatMessage]", "reducer": "append",
         "writers": part_names + [mgr_id], "readers": part_names + [mgr_id]}
    )
    return _wrap(nodes, edges, channels, provenance, start_nodes=_graphflow_entry(team, is_graphflow),
                 output_nodes=[])


def _manager_class(team):
    """The manager class, from the return annotation of ``_create_group_chat_manager_factory``, or None."""
    import typing

    factory = getattr(type(team), "_create_group_chat_manager_factory", None)
    try:
        ret = typing.get_type_hints(factory).get("return")
    except Exception:
        return None
    args = typing.get_args(ret)
    cls = args[-1] if args else None
    return cls if inspect.isclass(cls) else None


def _response_message_classes() -> list:
    """The classes the type of ``Response.chat_message`` admits."""
    import typing

    try:
        from autogen_agentchat.base import Response

        t = typing.get_type_hints(Response).get("chat_message")
    except Exception:
        return []
    args = typing.get_args(t)
    return [m for m in (args or (t,)) if inspect.isclass(m)]


def _manager_accepted_classes(team) -> list:
    """Response classes, narrowed by a guard over the manager's message thread."""
    declared = _response_message_classes()
    cls = _manager_class(team)
    guarded = _thread_guarded_message_classes(cls) if cls is not None else None
    if guarded is None:
        return declared
    return [m for m in declared if any(issubclass(m, g) for g in guarded)] or guarded


def _graphflow_obj(team):
    return getattr(team, "_graph", None) or getattr(team, "graph", None)


def _graphflow_entry(team, is_graphflow):
    if not is_graphflow:
        return []
    g = _graphflow_obj(team)
    if g is None:
        return []
    for attr in ("default_start_node", "_default_start_node", "entry_point", "_entry_point"):
        v = getattr(g, attr, None)
        if v:
            return [v if isinstance(v, str) else _safe_name(v, str(v))]
    return []


def _graphflow_edges(team, name_to_id):
    g = _graphflow_obj(team)
    edges = []
    if g is None:
        return edges
    nodes_map = getattr(g, "nodes", None)
    if not isinstance(nodes_map, dict):
        return edges
    for src_name, gnode in nodes_map.items():
        out_edges = getattr(gnode, "edges", None) or []
        for ge in out_edges:
            tgt = getattr(ge, "target", None)
            cond = getattr(ge, "condition", None)
            cond_repr = None
            branch = None
            if cond is not None:
                if isinstance(cond, str):
                    cond_repr = cond
                    branch = cond
                else:
                    cond_repr = "callable"
            edges.append(
                {"from": {"node": name_to_id.get(src_name, src_name), "socket": ""},
                 "to": {"node": name_to_id.get(tgt, tgt), "socket": ""},
                 "kind": "conditional" if cond is not None else "control",
                 "branch": branch, "condition": cond_repr}
            )
    return edges


def _annotate_graphflow_joins(team, nodes):
    """Record each GraphFlow node's ``activation`` (all/any)."""
    g = _graphflow_obj(team)
    if g is None:
        return
    nodes_map = getattr(g, "nodes", None)
    if not isinstance(nodes_map, dict):
        return
    by_name = {n["name"]: n for n in nodes}
    for name, gnode in nodes_map.items():
        act = getattr(gnode, "activation", None)
        if act is not None and name in by_name:
            by_name[name]["attrs"]["activation"] = str(act)


# --- autogen-core pub/sub runtime ---

def _registered_agents(runtime) -> list[tuple[str, type, object]]:
    """``(type name, agent class, factory)`` per registered type, from the closure of its factory wrapper."""
    wrappers = getattr(runtime, "_agent_factories", None)
    if not isinstance(wrappers, dict):
        raise ValueError(f"cannot read the agent types registered with the runtime {type(runtime).__name__}")
    agents = []
    for name, wrapper in wrappers.items():
        held = inspect.getclosurevars(wrapper).nonlocals
        cls = held.get("expected_class")
        if not inspect.isclass(cls):
            raise ValueError(f"cannot read the class that the agent type {name!r} was registered with")
        agents.append((str(name), cls, held.get("agent_factory")))
    return agents


def _runtime_subscriptions(runtime) -> list:
    subscriptions = getattr(getattr(runtime, "_subscription_manager", None), "_subscriptions", None)
    if not isinstance(subscriptions, list):
        raise ValueError(f"cannot read the subscriptions of the runtime {type(runtime).__name__}")
    return subscriptions


def _agent_instance(runtime, agent_type: str, factory):
    """An agent built by its factory in the runtime's instantiation context, or None."""
    from autogen_core import AgentId, AgentInstantiationContext

    try:
        with AgentInstantiationContext.populate_context((runtime, AgentId(agent_type, "default"))):
            agent = factory()
    except Exception:
        return None
    if inspect.isawaitable(agent):
        getattr(agent, "close", lambda: None)()
        return None
    return agent


def _extract_v04_pubsub(runtime, provenance) -> dict:
    """The topic graph of an unstarted autogen-core runtime: agents and the topics they subscribe and publish to."""
    from autogen_core import TopicId

    nodes, edges, channels = [], [], []
    agents = _registered_agents(runtime)
    subscriptions = _runtime_subscriptions(runtime)
    subscribed = {
        name: {s.topic_type for s in subscriptions if s.agent_type == name and isinstance(getattr(s, "topic_type", None), str)}
        for name, _, _ in agents
    }
    publishes: dict[str, set[str]] = {}
    for name, cls, factory in agents:
        read = _agent_publishes(cls, _agent_instance(runtime, name, factory))
        if read is None:
            raise ValueError(f"cannot read the source of the agent class {cls.__module__}.{cls.__name__}")
        topics, on_arrival_topic = read
        # publishing on ctx.topic_id reaches every topic the agent subscribes to
        publishes[name] = topics | (subscribed[name] if on_arrival_topic else set())
        nodes.append(
            {"id": name, "type_name": f"{cls.__module__}.{cls.__name__}", "kind": "agent", "name": name,
             "attrs": {"subscribes": ",".join(sorted(subscribed[name])), "publishes": ",".join(sorted(publishes[name]))}}
        )
    topics_seen: dict[str, dict] = {}
    for topic in sorted(set().union(*publishes.values(), *subscribed.values())):
        receivers = {s.agent_type for s in subscriptions if s.is_match(TopicId(type=topic, source="default"))}
        topics_seen[topic] = {
            "writers": sorted(name for name, topics in publishes.items() if topic in topics),
            "readers": sorted(name for name, _, _ in agents if name in receivers),
        }

    for topic, wr in topics_seen.items():
        tid = f"topic:{topic}"
        # a topic is a component node, so publishing and subscribing are edges agent -> topic -> agent
        nodes.append({"id": tid, "type_name": "topic", "kind": "component", "name": topic,
                      "attrs": {"topic": topic, "is_topic": "true"}})
        channels.append({"name": topic, "type_repr": "Message", "reducer": "append",
                         "writers": sorted(set(wr["writers"])), "readers": sorted(set(wr["readers"]))})
        for w in wr["writers"]:
            edges.append({"from": {"node": w, "socket": ""}, "to": {"node": tid, "socket": ""},
                          "kind": "pub-sub", "branch": "publish"})
        for r in wr["readers"]:
            edges.append({"from": {"node": tid, "socket": ""}, "to": {"node": r, "socket": ""},
                          "kind": "pub-sub", "branch": "subscribe"})
    return _wrap(nodes, edges, channels, provenance, start_nodes=[], output_nodes=[])
