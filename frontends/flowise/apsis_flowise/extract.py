"""Parse a Flowise flow.json (chatflow, AgentFlow V2 or Sequential Agents) into the apsis IR."""
from __future__ import annotations

import json
import re

from .nodekind import _node_kind
from .sockets import _input_sockets, _output_sockets
from .edges import _edge_kind, _resolve_socket
from .channels import _state_channels
from .refs import (
    _INSTANCE_REF,
    _declared_targets,
    _iter_strings,
    _selected_tool_ids,
    _subflow_ref,
)


# Flowise template variables are single-brace `{var}`.
_TMPL_VAR = re.compile(r"\{([a-zA-Z_]\w*)\}")
_PROMPT_FIELDS = (
    "template", "systemMessagePrompt", "humanMessagePrompt", "systemMessage", "promptText",
    "workerPrompt", "supervisorPrompt",
)
# filled from the chat input
_AUTOFILLED_VARS = {"question", "input"}


def _requires_vars(data: dict) -> list[str]:
    """The prompt's `{var}`s that need a binding: not filled from the chat input or set in ``promptValues``."""
    inputs = data.get("inputs") or {}
    text = " ".join(str(inputs.get(k, "")) for k in _PROMPT_FIELDS)
    vars_ = set(_TMPL_VAR.findall(text))
    pv = inputs.get("promptValues")
    if isinstance(pv, str) and pv.strip().startswith("{"):
        try:
            vars_ -= set(json.loads(pv).keys())
        except Exception:
            pass
    return sorted(vars_ - _AUTOFILLED_VARS)


# The anchor through which a Sequential Agents node takes its predecessors.
_SEQ_FLOW_INPUT = "sequentialNode"


def _reads_all_in_edges_as_flow(raw_node: dict | None) -> bool:
    """A Sequential Agents condition node, whose every in-edge the engine takes as a graph edge."""
    data = (raw_node or {}).get("data") or {}
    if not str(data.get("name") or "").startswith("seqCondition"):
        return False
    return any(a.get("name") == _SEQ_FLOW_INPUT for a in data.get("inputAnchors") or [] if isinstance(a, dict))


def extract(flow: dict, provenance: dict, framework_version: str | None = None) -> dict:
    nodes_raw = flow.get("nodes") or []
    edges_raw = flow.get("edges") or []
    id_set = {n.get("id") for n in nodes_raw}

    kinds: dict[str, str] = {}
    nodes: list[dict] = []
    start_nodes: list[str] = []
    output_nodes: list[str] = []

    for n in nodes_raw:
        data = n.get("data", {})
        nid = n.get("id")
        kind = _node_kind(data)
        kinds[nid] = kind

        node: dict = {
            "id": nid,
            "type_name": data.get("name") or data.get("label") or "unknown",
            "kind": kind,
            "inputs": _input_sockets(data),
            "outputs": _output_sockets(data, kind),
            "attrs": {},
        }

        # declared routing name
        inputs = data.get("inputs") or {}
        for nkey in ("supervisorName", "workerName", "agentName", "llmNodeName", "executeFlowName",
                     "chainName", "llmNodeLabel"):
            if isinstance(inputs.get(nkey), str) and inputs[nkey].strip():
                node["name"] = inputs[nkey].strip()
                break
        if "name" not in node and isinstance(data.get("label"), str):
            node["name"] = data["label"]

        # Flowise prompt nodes take their variable values through the `promptValues` input.
        rv = _requires_vars(data)
        if rv:
            node["requires_vars"] = rv
        if any(s["name"] == "promptValues" for s in node["inputs"]):
            node["attrs"]["template_values_input"] = "promptValues"

        sr = _subflow_ref(data)
        if sr is not None:
            node["subflow_ref"] = sr

        dt = _declared_targets(data, id_set)
        if dt:
            node["declared_targets"] = dt

        # An AgentFlow V2 condition takes exactly one transition.
        if kind == "router" and "Agentflow" in str(data.get("name") or ""):
            node["attrs"]["branch_outputs"] = "transition"
        # The AgentFlow engine moves an agent on without an out-edge (back to its supervisor or condition).
        if kind == "agent":
            node["attrs"]["implicit_return"] = "true"

        if data.get("category"):
            node["attrs"]["category"] = str(data["category"])
        if data.get("type"):
            node["attrs"]["flow_type"] = str(data["type"])
        if isinstance(inputs.get("maxLoopCount"), (str, int)):
            node["attrs"]["max_loop_count"] = str(inputs["maxLoopCount"])
        if inputs.get("recursionLimit") is not None:
            node["attrs"]["recursion_limit"] = str(inputs["recursionLimit"])

        if kind == "start":
            start_nodes.append(nid)
        if kind == "end":
            output_nodes.append(nid)

        nodes.append(node)

    # A `{{ producer.data.instance }}` input binds by reference, often with no edge in the export: add one.
    ref_consumers: dict[str, list[tuple[str, str]]] = {}  # producer -> [(consumer, socket)]
    existing_pairs = {
        (e.get("source"), e.get("target")) for e in edges_raw
    }
    instance_edges: list[dict] = []
    for n in nodes_raw:
        cid = n.get("id")
        inputs = (n.get("data") or {}).get("inputs") or {}
        for field, val in inputs.items():
            for s in _iter_strings(val):
                for prod in _INSTANCE_REF.findall(s):
                    ref_consumers.setdefault(prod, []).append((cid, field))
                    if prod in id_set and (prod, cid) not in existing_pairs:
                        existing_pairs.add((prod, cid))
                        instance_edges.append(
                            {
                                "from": {"node": prod, "socket": ""},
                                "to": {"node": cid, "socket": field},
                                "kind": _edge_kind(prod, field, None, kinds),
                            }
                        )

    # A producer referenced by two or more consumers is one instance shared by them.
    for prod, consumers in ref_consumers.items():
        if prod not in id_set:
            continue
        uniq = sorted({c for c, _ in consumers})
        if len(uniq) >= 2:
            iid = f"instance:{prod}"
            for node in nodes:
                if node["id"] == prod:
                    node["instance_id"] = iid

    # A reference to a missing node becomes a declared target, so target resolution flags it.
    node_by_id = {nd["id"]: nd for nd in nodes}
    for prod, consumers in ref_consumers.items():
        if prod in id_set:
            continue
        for cid, _field in consumers:
            nd = node_by_id.get(cid)
            if nd is not None:
                dts = nd.setdefault("declared_targets", [])
                if prod not in dts:
                    dts.append(prod)

    # Nodes that select the same tool/config UUID share one mutable instance.
    tool_id_owners: dict[str, list[str]] = {}
    for n in nodes_raw:
        for tid in set(_selected_tool_ids(n.get("data") or {})):
            tool_id_owners.setdefault(tid, []).append(n.get("id"))
    by_node: dict[str, str] = {}
    for tid, owners in tool_id_owners.items():
        if len(set(owners)) >= 2:
            for o in owners:
                by_node.setdefault(o, f"tool-instance:{tid}")
    for node in nodes:
        if node.get("instance_id") is None and node["id"] in by_node:
            node["instance_id"] = by_node[node["id"]]

    edges: list[dict] = []
    by_raw_id = {n.get("id"): n for n in nodes_raw}
    for e in edges_raw:
        src, tgt = e.get("source"), e.get("target")
        if src is None or tgt is None:
            continue
        sh = e.get("sourceHandle", "")
        th = e.get("targetHandle", "")
        frm = _resolve_socket(sh, src, "source")
        to = _resolve_socket(th, tgt, "target")
        # branch anchor: AgentFlow `output-<n>` or IfElse returnTrue / returnFalse
        branch = None
        m = re.search(r"-output-(\d+)$", sh or "")
        if m:
            branch = f"output-{m.group(1)}"
        elif "returnTrue" in (sh or ""):
            branch = "true_result"
        elif "returnFalse" in (sh or ""):
            branch = "false_result"
        elif kinds.get(src) == "router" and frm["socket"]:
            branch = frm["socket"]
        kind = _edge_kind(src, to["socket"], branch, kinds)
        edge = {"from": frm, "to": to, "kind": kind}
        if branch is not None:
            edge["branch"] = branch
        edges.append(edge)
        # An edge into a condition node is also one into its `sequentialNode` (`compileSeqAgentsGraph`).
        if _reads_all_in_edges_as_flow(by_raw_id.get(tgt)) and to["socket"] != _SEQ_FLOW_INPUT:
            edges.append({"from": frm, "to": {"node": tgt, "socket": _SEQ_FLOW_INPUT}, "kind": "data"})

    edges.extend(instance_edges)

    channels = _state_channels(nodes_raw)

    # Multi-Agents: workers tied to a supervisor only by an instance ref write its turn channel concurrently.
    real_pairs = {(e.get("source"), e.get("target")) for e in edges_raw}
    sup_workers: dict[str, list[str]] = {}
    for n in nodes_raw:
        data = n.get("data") or {}
        if data.get("name") != "worker":
            continue
        sup_ref = (data.get("inputs") or {}).get("supervisor")
        ref = sup_ref if isinstance(sup_ref, str) else ""
        for prod in _INSTANCE_REF.findall(ref):
            if (prod, n.get("id")) not in real_pairs:
                sup_workers.setdefault(prod, []).append(n.get("id"))
    for sup_id, workers in sup_workers.items():
        if len(workers) >= 2:
            sup_data = next((nd.get("data", {}) for nd in nodes_raw if nd.get("id") == sup_id), {})
            sname = (sup_data.get("inputs") or {}).get("supervisorName") or sup_id
            channels.append({
                "name": f"supervisor:{sname}",
                "type_repr": "Any",
                "reducer": "last-value",
                "writers": workers,
                "readers": [sup_id],
            })

    return {
        "execution_model": "visual-dataflow",
        "framework": "flowise",
        "framework_version": framework_version,
        "provenance": provenance,
        "nodes": nodes,
        "edges": edges,
        "channels": channels,
        "start_nodes": start_nodes,
        "output_nodes": output_nodes,
    }
