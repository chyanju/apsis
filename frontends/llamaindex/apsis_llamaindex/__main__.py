"""apsis LlamaIndex front-end: emit the apsis IR (JSON) for built LlamaIndex workflows."""
from __future__ import annotations

from apsis_common.cli import run

from .extract import extract
from .load import get_workflows


def main(argv: list[str] | None = None) -> int:
    return run(
        prog="apsis_llamaindex",
        description="emit the apsis IR (JSON) for a LlamaIndex workflow, or a list of workflows",
        spec_help="module:attr | file.py:attr",
        load=get_workflows,
        extract=extract,
        suppress_stdout=True,
        argv=argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
