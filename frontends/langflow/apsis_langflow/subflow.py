"""langflow sub-flows (RunFlow / FlowTool): the embedded-flow index, the referenced flow, and port bindings."""
from __future__ import annotations

from .scheduling import _release
from .typecanon import _as_list


def _referenced_flow_key(node_def: dict, node_data: dict) -> str | None:
    """The name or id of the sub-flow a node references, if any; releases store it under different keys."""
    if node_data.get("referenced_flow"):
        return node_data["referenced_flow"]
    for k in ("flow_name_selected", "flow_id_selected", "referenced_flow"):
        if node_def.get(k):
            return node_def[k]
    tmpl = node_def.get("template", {}) or {}
    for k in ("flow_name", "flow_name_selected", "flow_id_selected"):
        field = tmpl.get(k)
        if isinstance(field, dict):
            if field.get("value"):
                return field["value"]
            opts = field.get("options")
            if isinstance(opts, list) and opts:
                return opts[0]
    return None


def _subflow_index(flow: dict) -> dict:
    """Every embedded sub-flow by name and by id -> ``{name, id, flow}``."""
    index: dict[str, dict] = {}
    refd = flow.get("referenced_flows", {}) or {}
    if isinstance(refd, dict):
        for name, sub in refd.items():
            if isinstance(sub, dict):
                entry = {"name": name, "id": name, "flow": sub}
                index[name] = entry
    subs = flow.get("subflows", {}) or {}
    if isinstance(subs, dict):
        for fid, sub in subs.items():
            if isinstance(sub, dict):
                name = sub.get("name", fid)
                entry = {"name": name, "id": fid, "flow": sub}
                index[fid] = entry
                index[name] = entry
    return index


def _exposed_subflow_bindings(node_def: dict) -> list[tuple[str, str, str]]:
    """``(key, inner_node, inner_field)`` of each template key ``<innerNodeId>|<field>`` (older: ``~``)."""
    out = []
    tmpl = node_def.get("template", {}) or {}
    for key in tmpl:
        sep = "|" if "|" in key else ("~" if "~" in key else None)
        if sep is not None:
            inner_node, _, inner_field = key.partition(sep)
            if inner_node and inner_field:
                out.append((key, inner_node, inner_field))
    return out


# langflow's `OUTPUT_COMPONENTS`: a vertex whose id contains one (or that sets `is_output`) is an output vertex.
_OUTPUT_COMPONENTS = ("ChatOutput", "TextOutput", "DataOutput")

# output methods of `RunFlowBaseComponent` (from 1.1.2)
_RUN_FLOW_BASE_METHODS = ("data_output", "dataframe_output", "message_output")


def _output_vertices(sub_flow: dict) -> list[dict]:
    nodes = (sub_flow.get("data", {}) or {}).get("nodes", []) or []
    out = []
    for rn in nodes:
        if not isinstance(rn, dict):
            continue
        node_def = (rn.get("data", {}) or {}).get("node", {}) or {}
        if any(c in str(rn.get("id", "")) for c in _OUTPUT_COMPONENTS) or node_def.get("is_output"):
            out.append(rn)
    return out


def _run_flow_output_bindings(node_def: dict, parent_node_id: str, sub_flow: dict, version) -> list[dict]:
    """What each output of a step that runs a sub-flow reads from it, by output method and release."""
    bindings = []
    verts = _output_vertices(sub_flow)
    release = _release(version)
    for out in node_def.get("outputs", []):
        if not isinstance(out, dict):
            continue
        name, method = out.get("name", ""), out.get("method", "")
        outer = {"node": parent_node_id, "socket": name}
        if "~" in name:
            vertex, _, inner = name.partition("~")
            bindings.append({"outer": outer, "inner": {"node": vertex, "socket": inner}})
        elif method == "generate_results":
            # up to 1.0.x: every output vertex result; one that is not a Message is wrapped in a Data
            for v in verts:
                for o in ((v.get("data", {}) or {}).get("node", {}) or {}).get("outputs", []) or []:
                    if isinstance(o, dict) and o.get("name"):
                        b = {"outer": outer, "inner": {"node": v.get("id", ""), "socket": o["name"]}}
                        if "Message" not in _as_list(o.get("types")):
                            b["converted"] = True
                        bindings.append(b)
        elif method in _RUN_FLOW_BASE_METHODS and (release is None or release < (1, 4, 2)):
            # up to 1.4.1: the result named message of the first output vertex (any may be first), converted
            for v in verts:
                bindings.append({"outer": outer, "inner": {"node": v.get("id", ""), "socket": "message"}, "converted": True})
    return bindings


def _output_subflow_bindings(node_def: dict, parent_node_id: str) -> list[dict]:
    """The output ``PortBinding``s declared in ``outputs[].subflow_output_binding(s)``."""
    bindings = []
    for out in node_def.get("outputs", []):
        if not isinstance(out, dict):
            continue
        out_name = out.get("name", "")
        entries = _as_list(out.get("subflow_output_bindings"))
        single = out.get("subflow_output_binding")
        if isinstance(single, dict):
            entries.append(single)
        for b in entries:
            if not isinstance(b, dict):
                continue
            bindings.append(
                {
                    "outer": {"node": parent_node_id, "socket": out_name},
                    "inner": {"node": b.get("node", ""), "socket": b.get("output", "")},
                }
            )
    return bindings
