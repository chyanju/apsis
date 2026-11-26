"""Parse an exported langflow flow into the apsis IR: one ``Workflow`` per flow and embedded sub-flow."""
from __future__ import annotations

from .edges import _build_edges, _start_output_nodes
from .nodes import _build_node
from .scheduling import scheduling_facts
from .subflow import (
    _exposed_subflow_bindings,
    _output_subflow_bindings,
    _referenced_flow_key,
    _run_flow_output_bindings,
    _subflow_index,
)


def _build_workflow(
    flow_dict: dict, framework_version: str | None, wf_id: str | None, release: str | None = None
) -> dict:
    """One IR ``Workflow``; ``release`` is the langflow release the flow was made with, when known."""
    data = flow_dict.get("data", {}) or {}
    raw_nodes = data.get("nodes", []) or []
    raw_edges = data.get("edges", []) or []

    nodes = [_build_node(rn) for rn in raw_nodes if isinstance(rn, dict)]
    node_kinds = {n["id"]: n["kind"] for n in nodes}
    by_id = {n["id"]: n for n in nodes}

    # Link each RunFlow / FlowTool node to its embedded sub-flow, with the port bindings.
    sub_index = _subflow_index(flow_dict)
    for rn in raw_nodes:
        if not isinstance(rn, dict):
            continue
        node_data = rn.get("data", {}) or {}
        node_def = node_data.get("node", {}) or {}
        node_id = rn.get("id") or node_data.get("id") or node_data.get("type", "")
        node = by_id.get(node_id)
        if node is None or node.get("kind") != "subflow":
            continue
        ref = _referenced_flow_key(node_def, node_data)
        target_id = None
        if ref is not None and ref in sub_index:
            target_id = sub_index[ref]["id"]
        in_bindings = []
        for key, inner_node, inner_field in _exposed_subflow_bindings(node_def):
            in_bindings.append(
                {
                    "outer": {"node": node_id, "socket": key},
                    "inner": {"node": inner_node, "socket": inner_field},
                }
            )
        out_bindings = _output_subflow_bindings(node_def, node_id)
        if not out_bindings and target_id is not None:
            out_bindings = _run_flow_output_bindings(node_def, node_id, sub_index[ref]["flow"], release)
        node["subflow_ref"] = {
            "workflow": target_id if target_id is not None else (ref or ""),
            "in_bindings": in_bindings,
            "out_bindings": out_bindings,
        }

    edges = _build_edges(raw_edges, node_kinds)
    starts, outs = _start_output_nodes(nodes)
    raw_outputs = {}
    for rn in raw_nodes:
        if isinstance(rn, dict):
            nd = rn.get("data", {}) or {}
            raw_outputs[rn.get("id") or nd.get("id") or nd.get("type", "")] = (nd.get("node", {}) or {}).get("outputs", []) or []
    scheduling_facts(nodes, edges, release, raw_outputs)

    wf = {
        "execution_model": "visual-dataflow",
        "framework": "langflow",
        "nodes": nodes,
        "edges": edges,
        "channels": [],
        "start_nodes": starts,
        "output_nodes": outs,
    }
    if framework_version:
        wf["framework_version"] = framework_version
    if wf_id is not None:
        wf["id"] = wf_id
    return wf


def extract(flow: dict, provenance: dict, framework_version: str | None = None) -> dict:
    """A bare ``Workflow``, or a ``Program`` with the main flow (id ``main``) first when it embeds sub-flows."""
    sub_index = _subflow_index(flow)
    has_subs = bool(sub_index)

    main_id = "main" if has_subs else None
    release = framework_version or flow.get("last_tested_version")
    main = _build_workflow(flow, framework_version, main_id, release)
    main["provenance"] = provenance

    if not has_subs:
        return main

    workflows = [main]
    seen_ids = set()
    for entry in sub_index.values():
        fid = entry["id"]
        if fid in seen_ids:
            continue
        seen_ids.add(fid)
        sub_wf = _build_workflow(entry["flow"], framework_version, fid, release)
        sub_wf["provenance"] = {
            "kind": "flow-json",
            "path": provenance.get("path"),
            "extractor": "langflow:subflow",
        }
        workflows.append(sub_wf)

    return {"workflows": workflows}
