"""Introspect a LangGraph ``StateGraph`` builder into the IR base facts; the backend derives the graph relations."""
from __future__ import annotations

import inspect
from typing import get_type_hints

try:
    from langgraph.version import __version__ as LG_VERSION
except Exception:  # pragma: no cover
    try:
        from importlib.metadata import version as _ver

        LG_VERSION = _ver("langgraph")
    except Exception:
        LG_VERSION = None

START = "__start__"
END = "__end__"


from .schema import _builder_schema, _channels_from_schema, _registered_schemas, _required_keys
from .astutil import (
    _ast_command_send_targets,
    _injected_args,
    _node_func,
    _path_func,
    _read_channels,
    _router_return_targets,
    _send_only_targets,
    _send_payload_keys,
    _write_info,
    _node_source_ast,
)
from .nodekind import _is_subgraph, _node_kind, _tool_funcs, _tool_names


def _extract_workflow(builder, wf_id: str | None) -> tuple[dict, list]:
    """Return ``(workflow, child_builders)``, a child being ``(id, builder, keeps_state)`` per subgraph."""
    state_schema = _builder_schema(builder, "state")
    input_schema = _builder_schema(builder, "input")
    # managed values (RemainingSteps, IsLastStep) are computed per read, not channels
    managed_keys = set(getattr(builder, "managed", {}) or {})
    channel_descs = {k: v for k, v in _channels_from_schema(state_schema).items() if k not in managed_keys}
    # every registered schema adds channels, not only the state schema (as in StateGraph.channels)
    for schema in _registered_schemas(builder):
        if schema is state_schema:
            continue
        for cn, desc in _channels_from_schema(schema).items():
            if cn not in managed_keys:
                channel_descs.setdefault(cn, desc)
    channel_names = set(channel_descs.keys())

    branches = getattr(builder, "branches", {}) or {}
    branch_srcs = set(branches.keys())

    node_specs = dict(getattr(builder, "nodes", {}) or {})
    nodes_json: list[dict] = []
    child_builders: list[tuple[str, object, bool]] = []

    writers: dict[str, set[str]] = {c: set() for c in channel_names}
    readers: dict[str, set[str]] = {c: set() for c in channel_names}

    edges_json: list[dict] = []

    # nodes reached via Send from a node body, a bound tool or a routing function
    fanout_targets: set[str] = set()
    for _spec in node_specs.values():
        _f = _node_func(_spec)
        if _f is not None:
            fanout_targets.update(_send_only_targets(_f))
        for _tf in _tool_funcs(_spec):
            fanout_targets.update(_send_only_targets(_tf))
    for _named in branches.values():
        for _branch in _named.values():
            _path = getattr(_branch, "path", None)
            _pf = getattr(_path, "func", _path)  # unwrap a RunnableCallable to its function
            if callable(_pf):
                fanout_targets.update(_send_only_targets(_pf))

    for name, spec in node_specs.items():
        func = _node_func(spec)
        goto_targets, uses_parent, has_send, goto_unresolved = (
            _ast_command_send_targets(func) if func else ([], False, False, False)
        )
        # A node body that cannot be read may route to any node.
        if func is not None and _node_source_ast(func) is None:
            goto_unresolved = True
        tool_funcs = _tool_funcs(spec)
        tool_injected = any(_injected_args(f) for f in tool_funcs)
        for tf in tool_funcs:
            tg, tup, tsend, tunres = _ast_command_send_targets(tf)
            goto_targets = goto_targets + [t for t in tg if t not in goto_targets]
            uses_parent = uses_parent or tup
            has_send = has_send or tsend
            goto_unresolved = goto_unresolved or tunres
        # ends: the targets of a Command[Literal[...]] return annotation
        ends = list(getattr(spec, "ends", ()) or ())
        declared = []
        for t in list(ends) + list(goto_targets):
            if t not in declared:
                declared.append(t)

        is_sub = _is_subgraph(spec)
        kind = _node_kind(name, spec, func, has_send, goto_targets, branch_srcs)

        inputs = []
        outputs = []
        ret_keys: set[str] = set()
        full_update = False
        if func is not None:
            ret_keys, full_update = _write_info(func)
            reads = _read_channels(func, channel_names)
            injected = _injected_args(func)
            for cn in sorted(reads):
                desc = channel_descs.get(cn)
                sock = {
                    "name": cn,
                    "type_repr": desc["type_repr"] if desc else "Any",
                    "injected": injected,
                }
                if desc and desc["reducer"] != "last-value":
                    sock["reducer"] = desc["reducer"]
                inputs.append(sock)
                # a node started by Send(node, arg) reads arg, not the state
                if name not in fanout_targets:
                    readers.setdefault(cn, set()).add(name)
            for cn in sorted(ret_keys):
                desc = channel_descs.get(cn)
                outputs.append(
                    {
                        "name": cn,
                        "type_repr": desc["type_repr"] if desc else "Any",
                        "may_emit": name in branch_srcs or len(goto_targets) > 1,
                    }
                )
                if cn in writers:
                    writers[cn].add(name)
                else:
                    writers[cn] = {name}
        # a node with an input schema of its own reads that schema's required fields (attach_node)
        node_input = getattr(spec, "input_schema", None) or getattr(spec, "input", None)
        if node_input is not None and node_input is not state_schema and name not in fanout_targets and not is_sub:
            for cn in sorted(_required_keys(node_input) & channel_names):
                readers.setdefault(cn, set()).add(name)

        # a subgraph writes back every channel it shares with the parent, within its output schema
        in_bindings: list[dict] = []
        out_bindings: list[dict] = []
        if is_sub:
            cb = getattr(getattr(spec, "runnable", None), "builder", None)
            cs = _builder_schema(cb, "state")
            shared = (set(_channels_from_schema(cs)) & channel_names) if cs is not None else set()
            os_ = _builder_schema(cb, "output")
            if os_ is not None and os_ is not cs:
                oc = set(_channels_from_schema(os_))
                if oc:
                    shared &= oc
            for cn in sorted(shared):
                writers.setdefault(cn, set()).add(name)
            # handed in: the node's input channels the subgraph's input schema has (for a Send target, arg's keys)
            ci = _builder_schema(cb, "input") or cs
            sub_in = set(_channels_from_schema(ci)) if ci is not None else set()
            if name in fanout_targets:
                payload, known = set(), True
                callers = [_node_func(s) for s in node_specs.values()]
                callers += [getattr(getattr(b, "path", None), "func", getattr(b, "path", None))
                            for named in branches.values() for b in named.values()]
                for f in callers:
                    if callable(f):
                        k, ok = _send_payload_keys(f, name)
                        payload |= k
                        known = known and ok
                handed = (payload if known else sub_in) & sub_in
            else:
                node_in = set(_channels_from_schema(getattr(spec, "input_schema", None) or state_schema))
                handed = node_in & sub_in
            in_bindings = [{"outer": {"node": name, "socket": c}, "inner": {"node": START, "socket": c}}
                           for c in sorted(handed)]
            out_bindings = [{"outer": {"node": name, "socket": c}, "inner": {"node": END, "socket": c}}
                            for c in sorted(shared)]

        node = {
            "id": name,
            "type_name": _node_type_name(spec),
            "kind": kind,
            "inputs": inputs,
            "outputs": outputs,
            "instance_id": _instance_id(spec),
        }
        if declared:
            node["declared_targets"] = declared
        attrs: dict[str, str] = {}
        if uses_parent:
            attrs["command_parent"] = "true"
        if getattr(spec, "defer", False):
            attrs["defer"] = "true"
        tool_names = _tool_names(spec)
        if tool_names:
            attrs["tools"] = ",".join(tool_names)
        if has_send:
            attrs["uses_send"] = "true"
        if name in fanout_targets:
            attrs["fanout"] = "true"
        if tool_injected:
            attrs["injected_tool_args"] = "true"
        if full_update:
            attrs["full_state_update"] = "true"
        if goto_unresolved:
            # over-approximate: a goto target that cannot be evaluated may route anywhere
            attrs["goto_unresolved"] = "true"
        if attrs:
            node["attrs"] = attrs

        if is_sub:
            child_id = f"{wf_id or 'main'}::{name}"
            node["subflow_ref"] = {"workflow": child_id, "in_bindings": in_bindings, "out_bindings": out_bindings}
            # a subgraph compiled with checkpointer=True keeps its channels across runs
            child_builders.append((child_id, spec.runnable.builder, getattr(spec.runnable, "checkpointer", None) is True))

        nodes_json.append(node)

    # control edges (add_edge)
    for u, v in sorted(getattr(builder, "edges", set()) or set()):
        edges_json.append(
            {
                "from": {"node": u, "socket": ""},
                "to": {"node": v, "socket": ""},
                "kind": "control",
            }
        )

    # add_edge([s1, s2], dst): a wait-for-all join, kept in waiting_edges rather than edges
    barrier_joins: set[str] = set()
    for srcs, dst in getattr(builder, "waiting_edges", set()) or set():
        barrier_joins.add(dst)
        for u in srcs:
            edges_json.append({"from": {"node": u, "socket": ""}, "to": {"node": dst, "socket": ""}, "kind": "control"})
    for n in nodes_json:
        if n["id"] in barrier_joins:
            n.setdefault("attrs", {})["barrier_join"] = "true"

    # conditional edges (add_conditional_edges)
    all_ids = [n["id"] for n in nodes_json]
    # router facts go on the source node, so a router on START needs a START node
    if START in branches:
        nodes_json.append({"id": START, "type_name": "langgraph.constants.START", "kind": "start"})
    for src, named in branches.items():
        for branch_name, branch in named.items():
            ends = getattr(branch, "ends", None)
            path = getattr(branch, "path", None)
            rf = _path_func(path)
            rr = _router_return_targets(rf) if callable(rf) else {
                "labels": [], "gated": [], "annotation": [], "sends": [], "unresolved": True, "fanout": False}
            known = rr["labels"] + [t for t in rr["gated"] + rr["annotation"] + rr["sends"] if t not in rr["labels"]]
            # ends is a dict {label: node} or a list of node names (a path map), or None (no path map).
            targets: list[str] = []
            map_keys: list[str] | None = None
            if isinstance(ends, dict):
                targets = list(ends.values())
                map_keys = [str(k) for k in ends.keys()]
            elif isinstance(ends, (list, tuple, set)):
                targets = list(ends)
                map_keys = [str(k) for k in ends]
            elif known and not rr["unresolved"]:
                targets = list(known)
            else:
                # over-approximate as LangGraph does: the branch may route to any node or END
                targets = all_ids + [END]
            for n in nodes_json:
                if n["id"] == src:
                    a = n.setdefault("attrs", {})
                    if rr["labels"]:
                        a[f"router_returns:{branch_name}"] = ",".join(rr["labels"])
                    if rr["gated"]:
                        a[f"router_returns_gated:{branch_name}"] = ",".join(rr["gated"])
                    if rr["sends"]:
                        a[f"router_sends:{branch_name}"] = ",".join(rr["sends"])
                    if map_keys is not None:
                        a[f"router_map:{branch_name}"] = ",".join(map_keys)
                    if rr["unresolved"]:
                        a[f"router_unresolved:{branch_name}"] = "true"
                    if rr["fanout"]:
                        a[f"router_fanout:{branch_name}"] = "true"
            # a router annotated with the graph's input schema sees only that schema's channels
            if rf is not None and input_schema is not None and input_schema is not state_schema:
                try:
                    first = next(iter(inspect.signature(rf).parameters))
                    ann = get_type_hints(rf).get(first)
                except Exception:
                    ann = None
                if ann is input_schema:
                    input_keys = set(getattr(ann, "__annotations__", {}) or {})
                    filtered = _read_channels(rf, channel_names) - input_keys
                    if filtered:
                        for n in nodes_json:
                            if n["id"] == src:
                                n.setdefault("attrs", {})["router_filtered_reads"] = ",".join(sorted(filtered))
            for dst in targets:
                edges_json.append(
                    {
                        "from": {"node": src, "socket": ""},
                        "to": {"node": dst, "socket": ""},
                        "kind": "conditional",
                        "branch": branch_name,
                    }
                )
            for n in nodes_json:
                if n["id"] == src:
                    dts = n.setdefault("declared_targets", [])
                    for dst in targets:
                        if dst not in dts:
                            dts.append(dst)

    # handoff edges: declared targets without a control or conditional edge
    existing = {(e["from"]["node"], e["to"]["node"]) for e in edges_json}
    for n in nodes_json:
        if n.get("kind") == "subflow":
            continue
        for t in n.get("declared_targets", []):
            if (n["id"], t) not in existing and t not in (START, END):
                edges_json.append(
                    {
                        "from": {"node": n["id"], "socket": ""},
                        "to": {"node": t, "socket": ""},
                        "kind": "handoff",
                    }
                )
                existing.add((n["id"], t))

    channels_json = []
    for cn, desc in channel_descs.items():
        channels_json.append(
            {
                "name": cn,
                "type_repr": desc["type_repr"],
                "reducer": desc["reducer"],
                "writers": sorted(writers.get(cn, set())),
                "readers": sorted(readers.get(cn, set())),
            }
        )

    start_nodes = sorted({v for (u, v) in (getattr(builder, "edges", set()) or set()) if u == START})
    for src in branch_srcs:
        if src == START:
            for named in branches.get(src, {}).values():
                ends = getattr(named, "ends", None)
                if isinstance(ends, dict):
                    start_nodes.extend(ends.values())
                elif isinstance(ends, (list, tuple, set)):
                    start_nodes.extend(ends)
    start_nodes = sorted(set(start_nodes))
    output_nodes = sorted({u for (u, v) in (getattr(builder, "edges", set()) or set()) if v == END})

    wf = {
        "execution_model": "bsp-superstep",
        "framework": "langgraph",
        "framework_version": LG_VERSION,
        "nodes": nodes_json,
        "edges": edges_json,
        "channels": channels_json,
        "start_nodes": start_nodes,
        "output_nodes": output_nodes,
    }
    # the run's input sets the fields of the graph's input schema
    provided = set(_channels_from_schema(input_schema)) if input_schema is not None else set()
    wf["attrs"] = {"provided_channels": ",".join(sorted(provided & channel_names))}
    if wf_id is not None:
        wf["id"] = wf_id
    return wf, child_builders


def _node_type_name(spec) -> str:
    if _is_subgraph(spec):
        return "langgraph.graph.state.CompiledStateGraph"
    func = _node_func(spec)
    if func is not None:
        mod = getattr(func, "__module__", "") or ""
        qn = getattr(func, "__qualname__", None) or getattr(func, "__name__", "node")
        return f"{mod}.{qn}" if mod else qn
    r = getattr(spec, "runnable", None)
    return f"{type(r).__module__}.{type(r).__name__}" if r is not None else "node"


def _instance_id(spec) -> str | None:
    r = getattr(spec, "runnable", None)
    if _is_subgraph(spec):
        return hex(id(r))
    func = _node_func(spec)
    if func is not None:
        return hex(id(func))
    return hex(id(r)) if r is not None else None


def extract(builder, provenance: dict) -> dict:
    """The IR of a ``StateGraph`` builder: a workflow, or a ``Program`` with a workflow per compiled subgraph."""
    main, children = _extract_workflow(builder, wf_id="main")
    main["provenance"] = provenance

    workflows = [main]
    queue = list(children)
    seen_ids = {"main"}
    while queue:
        cid, cbuilder, keeps_state = queue.pop(0)
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        child_wf, grandchildren = _extract_workflow(cbuilder, wf_id=cid)
        child_wf["provenance"] = provenance
        if keeps_state:
            child_wf.setdefault("attrs", {})["keeps_state"] = "true"
        workflows.append(child_wf)
        queue.extend(grandchildren)

    if len(workflows) == 1:
        return main
    return {"workflows": workflows}
