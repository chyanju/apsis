"""Emit the apsis IR (JSON) for an exported langflow flow.json.

Usage: python -m apsis_langflow <path/to/flow.json> [-o out.json] [--framework-version X]
"""
from __future__ import annotations

from apsis_common.cli import run

from .extract import extract
from .load import load_flow


def main(argv: list[str] | None = None) -> int:
    return run(
        prog="apsis_langflow",
        description="emit the apsis IR (JSON) for an exported langflow flow.json",
        spec_help="path to a langflow exported flow.json",
        load=load_flow,
        extract=extract,
        version_help="set framework_version in the IR (langflow is parsed statically, so it is not detected)",
        argv=argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
