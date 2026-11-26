"""Load the Haystack pipeline of a ``module:attr``, ``file.py:attr`` or YAML spec, without running it.

The module's other ``Pipeline`` objects come along, so a component shared across pipelines is visible.
"""
from __future__ import annotations

import importlib
import os
import sys

from apsis_common.loader import load_py_module
from haystack import Pipeline


def _resolve(obj) -> Pipeline:
    pipe = obj() if callable(obj) and not isinstance(obj, Pipeline) else obj
    if not isinstance(pipe, Pipeline):
        raise TypeError(f"expected a haystack Pipeline, got {type(pipe).__name__}")
    return pipe


def _module_pipelines(mod, primary: Pipeline) -> list[Pipeline]:
    """Every distinct module-level ``Pipeline``, the entry one first (by identity, so an alias counts once)."""
    seen = {id(primary)}
    pipes = [primary]
    for val in vars(mod).values():
        if isinstance(val, Pipeline) and id(val) not in seen:
            seen.add(id(val))
            pipes.append(val)
    return pipes


def get_pipelines(spec: str) -> tuple[list[Pipeline], dict]:
    if spec.endswith((".yaml", ".yml")):
        with open(spec) as f:
            return [Pipeline.loads(f.read())], {"kind": "yaml", "path": spec, "extractor": "haystack"}
    if ":" not in spec:
        raise ValueError("spec must be 'module:attr', 'file.py:attr', or a .yaml file")

    target, _, attr = spec.partition(":")
    if target.endswith(".py") or os.path.exists(target):
        mod = load_py_module(target, "apsis_user_pipeline")
        kind = "import-file"
    else:
        if "" not in sys.path:  # make CWD importable so `module:attr` works without an install
            sys.path.insert(0, "")
        mod = importlib.import_module(target)
        kind = "import"
    primary = _resolve(getattr(mod, attr))
    return _module_pipelines(mod, primary), {"kind": kind, "path": spec, "extractor": "haystack"}
