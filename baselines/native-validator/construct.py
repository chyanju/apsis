"""Construct one code-first workflow with its framework and run the framework's own construction-time checks.

usage: <python of the framework's environment> -B construct.py FILE.py:ATTR
Prints one JSON line: {"ok": true, "type": ...} or {"ok": false, "stage": ..., "error": ...}.
"""
import importlib.util
import inspect
import json
import os
import sys
import traceback


def fail(stage, exc):
    print(json.dumps({"ok": False, "stage": stage, "error": f"{type(exc).__name__}: {exc}"[:400],
                      "where": traceback.format_exc().strip().splitlines()[-3:]}))
    sys.exit(0)


entry = sys.argv[1]
path, attr = entry.rsplit(":", 1)
sys.path.insert(0, os.path.dirname(os.path.abspath(path)))
try:
    spec = importlib.util.spec_from_file_location("native_validator_case", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["native_validator_case"] = mod
    spec.loader.exec_module(mod)
except BaseException as e:  # noqa: BLE001 - any failure while constructing counts as a rejection
    fail("construct", e)

try:
    obj = getattr(mod, attr)
    if inspect.isfunction(obj) or inspect.iscoroutinefunction(obj):
        obj = obj()
        if inspect.iscoroutine(obj):
            import asyncio
            obj = asyncio.run(obj)
    kind = f"{type(obj).__module__}.{type(obj).__name__}"
    if type(obj).__name__ == "StateGraph" and hasattr(obj, "compile"):
        obj.compile()
        kind += " (compiled here)"
    elif type(obj).__name__ == "WorkflowBuilder" and hasattr(obj, "build"):
        obj.build()
        kind += " (built here)"
except BaseException as e:  # noqa: BLE001
    fail("validate", e)
print(json.dumps({"ok": True, "type": kind}))
