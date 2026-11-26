"""Introspect a built Microsoft agent-framework ``Workflow`` and its sub-workflows into an apsis IR ``Program``."""
from __future__ import annotations

from .version import _AF_VERSION
from .resolve import (
    _chat_agent_workflow,
    _looks_like_workflow,
    _resolve_chat_agent,
    _resolve_workflow,
)
from .nodes import _build_node, _handoff_targets
from .edges import _edge_records
from .channels import _shared_state
from .load import SHARED


def _output_node_ids(workflow) -> list[str]:
    ids: list[str] = []
    try:
        for e in workflow.get_output_executors() or []:
            eid = getattr(e, "id", None) or (e if isinstance(e, str) else None)
            if eid is not None and str(eid) not in ids:
                ids.append(str(eid))
    except Exception:
        pass
    if not ids:
        od = getattr(workflow, "_output_designation", None)
        outs = getattr(od, "outputs", None) if od is not None else None
        if outs:
            for o in outs:
                eid = getattr(o, "id", None) or (o if isinstance(o, str) else None)
                if eid is not None and str(eid) not in ids:
                    ids.append(str(eid))
    # The SDK keeps the designation in a set; order the ids as the executors are.
    order = {str(eid): i for i, eid in enumerate(getattr(workflow, "executors", {}) or {})}
    return sorted(ids, key=lambda eid: order.get(eid, len(order)))


def _workflow_to_ir(workflow, wf_id: str | None, provenance: dict) -> tuple[dict, list]:
    """``(workflow_dict, [(child_id, child_workflow), ...])`` for one ``Workflow``."""
    nodes = []
    children: list[tuple[str, object]] = []
    hosts: list[tuple[dict, object]] = []
    for eid, ex in workflow.executors.items():
        node = _build_node(eid, ex)
        if node["kind"] == "subflow":
            sub = getattr(ex, "workflow", None) or getattr(ex, "_workflow", None)
            if _looks_like_workflow(sub):
                child_id = str(getattr(sub, "id", None) or getattr(sub, "name", None) or f"{eid}__sub")
                node["subflow_ref"] = {
                    "workflow": child_id,
                    "in_bindings": [],
                    "out_bindings": [],
                }
                # the host passes the sub-workflow's requests on to its own caller
                if getattr(ex, "propagate_request", False):
                    node["attrs"]["propagates_requests"] = "true"
                children.append((child_id, sub))
                hosts.append((node, sub))
        nodes.append(node)

    handoff_sources = {
        str(eid) for eid, ex in workflow.executors.items() if _handoff_targets(ex)
    }
    edges = []
    for eg in getattr(workflow, "edge_groups", []) or []:
        edges.extend(_edge_records(eg, handoff_sources))

    # A fan-in edge group hands its sources' messages to the target as one list.
    by_id = {node["id"]: node for node in nodes}
    for eg in getattr(workflow, "edge_groups", []) or []:
        if type(eg).__name__ == "FanInEdgeGroup":
            for e in getattr(eg, "edges", []) or []:
                target = by_id.get(str(getattr(e, "target_id", "")))
                if target is not None:
                    target.setdefault("attrs", {})["fan_in_delivery"] = "list"

    # A declared handoff target without a graph edge still gets a handoff edge, for target resolution.
    realized = {(e["from"]["node"], e["to"]["node"]) for e in edges}
    for node in nodes:
        for tgt in node.get("declared_targets", []):
            pair = (node["id"], tgt)
            if pair not in realized:
                edges.append(
                    {
                        "from": {"node": node["id"], "socket": ""},
                        "to": {"node": tgt, "socket": ""},
                        "kind": "handoff",
                    }
                )

    _bind_request_ports(hosts, nodes, edges)

    channels, reads_first = _shared_state(workflow)
    for node in nodes:
        if node["id"] in reads_first:
            node.setdefault("attrs", {})["reads_before_write"] = ", ".join(reads_first[node["id"]])

    start = getattr(workflow, "start_executor_id", None)
    start_nodes = [str(start)] if start else []
    output_nodes = _output_node_ids(workflow)

    wf = {
        "execution_model": "group-chat-speaker",
        "framework": "agent-framework",
        "framework_version": _AF_VERSION,
        "provenance": provenance,
        "id": wf_id or str(getattr(workflow, "id", None) or getattr(workflow, "name", None) or "main"),
        "nodes": nodes,
        "edges": edges,
        "channels": channels,
        "start_nodes": start_nodes,
        "output_nodes": output_nodes,
        "max_runs_per_component": _max_iterations(workflow),
    }
    return wf, children


def _bind_request_ports(hosts, nodes, edges) -> None:
    """Bind each request port of a sub-workflow to the parent steps that answer its host's requests."""
    by_id = {n["id"]: n for n in nodes}
    for host, sub in hosts:
        ports = [
            str(pid) for pid, pex in getattr(sub, "executors", {}).items() if _build_node(pid, pex)["attrs"].get("request_port")
        ]
        if not ports:
            continue
        answerers = [
            by_id[e["to"]["node"]]
            for e in edges
            if e["from"]["node"] == host["id"] and e["to"]["node"] in by_id
            and any(i["type_repr"] == "SubWorkflowRequestMessage" for i in by_id[e["to"]["node"]].get("inputs", []))
        ]
        for answerer in answerers:
            for port in ports:
                host["subflow_ref"]["in_bindings"].append(
                    {
                        "outer": {"node": answerer["id"], "socket": "SubWorkflowResponseMessage"},
                        "inner": {"node": port, "socket": ""},
                    }
                )


def _max_iterations(workflow):
    mi = getattr(workflow, "max_iterations", None)
    try:
        return int(mi) if mi is not None else None
    except (TypeError, ValueError):
        return None


def extract(entry_obj, provenance: dict) -> dict:
    """The IR ``Program`` of the entry object: one workflow per (sub-)workflow."""
    root = _resolve_workflow(entry_obj)
    if root is None:
        agent = _resolve_chat_agent(entry_obj)
        if agent is not None:
            return {"workflows": [_chat_agent_workflow(agent, provenance)]}
        raise TypeError(
            f"expected an agent-framework Workflow (or an object wrapping one), got "
            f"{type(entry_obj).__module__}.{type(entry_obj).__name__}"
        )

    workflows: list[dict] = []
    seen_ids: set[str] = set()
    main_id = str(getattr(root, "id", None) or getattr(root, "name", None) or "main")
    queue: list[tuple[str, object]] = [(main_id, root)]
    while queue:
        wf_id, wf = queue.pop(0)
        if wf_id in seen_ids:
            continue
        seen_ids.add(wf_id)
        wf_dict, children = _workflow_to_ir(wf, wf_id, provenance)
        workflows.append(wf_dict)
        for child_id, child_wf in children:
            if child_id not in seen_ids:
                queue.append((child_id, child_wf))

    if id(root) in SHARED:
        workflows[0]["attrs"] = {"shared_workflow": "true"}
    return {"workflows": workflows}
