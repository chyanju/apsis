"""apsis AutoGen front-end: emit the apsis IR (JSON) for a built orchestration object."""
from __future__ import annotations

from apsis_common.cli import run

from .extract import extract
from .load import get_workflow


def main(argv: list[str] | None = None) -> int:
    return run(
        prog="apsis_autogen",
        description="apsis AutoGen front-end — emit the apsis IR (JSON) for a built orchestration object.",
        spec_help="module:attr | file.py:attr",
        load=get_workflow,
        extract=extract,
        suppress_stdout=True,  # AutoGen logs client warnings to stdout; keep only the IR JSON there
        argv=argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
