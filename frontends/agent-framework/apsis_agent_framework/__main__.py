"""Emit the apsis IR (JSON) for a built Microsoft agent-framework workflow.

Usage: python -m apsis_agent_framework <module:attr | file.py:attr> [-o out.json]
"""
from __future__ import annotations

from apsis_common.cli import run

from .extract import extract
from .load import get_workflow


def main(argv: list[str] | None = None) -> int:
    return run(
        prog="apsis_agent_framework",
        description="emit the apsis IR (JSON) for a built Microsoft agent-framework workflow",
        spec_help="module:attr | file.py:attr",
        load=get_workflow,
        extract=extract,
        suppress_stdout=True,  # the entry module and SDK extras may print on import
        argv=argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
