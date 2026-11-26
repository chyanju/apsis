"""The shared ``python -m apsis_<framework>`` entry point: load, extract, print the IR JSON."""
from __future__ import annotations

import argparse
import contextlib
import json
import sys


def _apply_version(ir: dict, version: str) -> None:
    if "workflows" in ir:
        for wf in ir["workflows"]:
            wf["framework_version"] = version
    else:
        ir["framework_version"] = version


def run(
    *,
    prog: str,
    description: str,
    spec_help: str,
    load,
    extract,
    version_help: str = "override framework_version in the IR",
    suppress_stdout: bool = False,
    argv: list[str] | None = None,
) -> int:
    """Run a front-end CLI: ``load(spec) -> (obj, provenance)``, ``extract(obj, provenance) -> ir``."""
    ap = argparse.ArgumentParser(prog=prog, description=description)
    ap.add_argument("spec", help=spec_help)
    ap.add_argument("-o", "--out", help="write IR JSON here (default: stdout)")
    ap.add_argument("--framework-version", help=version_help)
    args = ap.parse_args(argv)

    quiet = contextlib.redirect_stdout(sys.stderr) if suppress_stdout else contextlib.nullcontext()
    real_stdout = sys.stdout
    try:
        with quiet:
            obj, provenance = load(args.spec)
    except Exception as e:
        print(f"{prog}: failed to load workflow from {args.spec!r}: {e}", file=sys.stderr)
        return 2
    try:
        with (contextlib.redirect_stdout(sys.stderr) if suppress_stdout else contextlib.nullcontext()):
            ir = extract(obj, provenance)
    except Exception as e:
        print(f"{prog}: failed to extract IR from {args.spec!r}: {e}", file=sys.stderr)
        return 3
    sys.stdout = real_stdout

    if args.framework_version:
        _apply_version(ir, args.framework_version)
    text = json.dumps(ir, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
    else:
        print(text)
    return 0
