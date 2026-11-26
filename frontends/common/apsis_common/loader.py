"""Resolve a ``module:attr`` or ``file.py:attr`` entry spec to the workflow object, without running it."""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys


def load_py_module(path: str, name: str = "apsis_user_module"):
    pkg_dir = os.path.dirname(os.path.abspath(path))
    if pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def resolve_entry(spec: str, resolve, extractor: str, *, module_name: str = "apsis_user_module"):
    """Return ``(resolve(attr), provenance)``; ``resolve`` must build, never run, the workflow."""
    if ":" not in spec:
        raise ValueError("spec must be 'module:attr' or 'file.py:attr'")
    target, _, attr = spec.partition(":")
    if target.endswith(".py") or os.path.exists(target):
        mod = load_py_module(target, module_name)
        kind = "import-file"
    else:
        if "" not in sys.path:  # make CWD importable so `module:attr` works without an install
            sys.path.insert(0, "")
        mod = importlib.import_module(target)
        kind = "import"
    return resolve(getattr(mod, attr)), {"kind": kind, "path": spec, "extractor": extractor}
