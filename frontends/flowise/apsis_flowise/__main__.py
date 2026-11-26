"""Emit the apsis IR (JSON) for a Flowise flow.json, read statically.

Usage: python -m apsis_flowise <path/to/flow.json> [-o out.json] [--framework-version X]
"""
from __future__ import annotations

from apsis_common.cli import run

from .extract import extract
from .load import get_flow


def main(argv: list[str] | None = None) -> int:
    return run(
        prog="apsis_flowise",
        description="emit the apsis IR (JSON) for a Flowise flow.json export",
        spec_help="path to a Flowise flow.json export",
        load=get_flow,
        extract=extract,
        version_help="set framework_version in the IR (Flowise version the flow targets)",
        argv=argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
