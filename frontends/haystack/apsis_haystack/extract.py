"""Introspect a built Haystack ``Pipeline`` into the IR base facts; the backend derives the graph relations."""
from __future__ import annotations

import ast
import inspect
import re
import textwrap

import haystack
from apsis_common.pytypes import canonicalize_python_type as _canon_type

try:
    from haystack.core.component.types import _empty
except ImportError:  # Haystack <= 2.0.0b5 keeps the default marker in the sockets module
    from haystack.core.component.sockets import _empty

_JINJA_VAR = re.compile(r"\{\{\s*([a-zA-Z_]\w*)")


def _haystack_version() -> str:
    version = getattr(haystack, "__version__", None)
    if version is None:  # releases before 2.0.0 define no __version__
        from importlib.metadata import version as package_version

        version = package_version("haystack-ai")
    return version


def _router_may_emit(routes: list, output_names: list[str]) -> set[str]:
    """``may_emit`` of a router: an output is conditional unless every route emits it."""
    guaranteed: set[str] | None = None
    for route in routes:
        emitted = {route.get("output_name")} if isinstance(route, dict) else set()
        guaranteed = emitted if guaranteed is None else (guaranteed & emitted)
    return set(output_names) - (guaranteed or set())


def _may_emit_outputs(instance, output_names: list[str]) -> set[str]:
    """Output keys the component may omit on some run; a non-literal ``return`` counts as emitting every key."""
    routes = getattr(instance, "routes", None)
    if isinstance(routes, list) and routes:
        return _router_may_emit(routes, output_names)
    if "Router" in type(instance).__name__:
        # a router whose routes cannot be read: every output is conditional
        return set(output_names)
    try:
        src = textwrap.dedent(inspect.getsource(type(instance).run))
        tree = ast.parse(src)
    except (OSError, TypeError, SyntaxError):
        return set()
    literal_return_keys: list[set[str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            keys = {
                k.value
                for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            literal_return_keys.append(keys)
    return {name for name in output_names if any(name not in keys for keys in literal_return_keys)}


def _type_str(t) -> str:
    if t is _empty or t is None:
        return "Any"
    if isinstance(t, type):
        return _canon_type(t.__name__)
    return _canon_type(str(t))


def _requires_vars(init_params: dict) -> list[str]:
    template = init_params.get("template")
    if isinstance(template, str):
        return sorted(set(_JINJA_VAR.findall(template)))
    return []


def _store_ref(instance) -> str | None:
    store = getattr(instance, "document_store", None)
    return hex(id(store)) if store is not None else None


def _writes_store(instance) -> bool:
    try:
        src = inspect.getsource(type(instance).run)
    except (OSError, TypeError):
        return False
    return "write_documents" in src or "delete_documents" in src


def extract(pipelines, provenance: dict) -> dict:
    if not isinstance(pipelines, list):
        pipelines = [pipelines]
    workflows = [_extract_one(p, provenance, "main" if i == 0 else f"pipeline_{i}") for i, p in enumerate(pipelines)]
    return workflows[0] if len(workflows) == 1 else {"workflows": workflows}


def _extract_one(pipeline, provenance: dict, wf_id: str) -> dict:
    d = pipeline.to_dict()
    comps = d.get("components", {})
    g = pipeline.graph

    nodes = []
    for name, data in g.nodes(data=True):
        inst = data["instance"]
        meta = comps.get(name, {})
        type_name = meta.get("type") or f"{type(inst).__module__}.{type(inst).__name__}"
        out_names = list(data.get("output_sockets", {}).keys())
        may_emit = _may_emit_outputs(inst, out_names)

        inputs = []
        # sorted: a component may build its sockets from a set, whose order varies between runs
        for sn, sock in sorted(data.get("input_sockets", {}).items()):
            inputs.append(
                {
                    "name": sn,
                    "type_repr": _type_str(getattr(sock, "type", None)),
                    "has_default": getattr(sock, "default_value", _empty) is not _empty,
                    "variadic": bool(getattr(sock, "is_variadic", False)),
                    "mandatory": bool(getattr(sock, "is_mandatory", False)),
                    "greedy": bool(getattr(sock, "is_greedy", False)),
                }
            )
        outputs = [
            {
                "name": sn,
                "type_repr": _type_str(getattr(sock, "type", None)),
                "may_emit": sn in may_emit,
            }
            for sn, sock in data.get("output_sockets", {}).items()
        ]

        store_ref = _store_ref(inst)
        store_role = None
        if store_ref is not None:
            writes = _writes_store(inst) or any(i["name"] == "documents" for i in inputs)
            store_role = "write" if writes else "read"

        nodes.append(
            {
                "id": name,
                "type_name": type_name,
                "inputs": inputs,
                "outputs": outputs,
                "requires_vars": _requires_vars(meta.get("init_parameters", {})),
                "instance_id": hex(id(inst)),
                "store_ref": store_ref,
                "store_role": store_role,
            }
        )

    edges = [
        {
            "from": {"node": u, "socket": data["from_socket"].name},
            "to": {"node": v, "socket": data["to_socket"].name},
        }
        for u, v, data in g.edges(data=True)
    ]

    return {
        "id": wf_id,
        "execution_model": "dataflow-readiness",
        "framework": "haystack",
        "framework_version": _haystack_version(),
        "provenance": provenance,
        "nodes": nodes,
        "edges": edges,
        # releases before 2.0.0 call it `max_loops_allowed`
        "max_runs_per_component": d.get("max_runs_per_component", d.get("max_loops_allowed")),
    }
