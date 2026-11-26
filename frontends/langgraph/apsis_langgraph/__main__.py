"""apsis LangGraph front-end: emit the apsis IR (JSON) for a compiled StateGraph."""
from __future__ import annotations

from apsis_common.cli import run

from .extract import extract
from .load import get_graph


def main(argv: list[str] | None = None) -> int:
    return run(
        prog="apsis_langgraph",
        description="emit the apsis IR (JSON) for a compiled LangGraph StateGraph",
        spec_help="module:attr | file.py:attr",
        load=get_graph,
        extract=extract,
        argv=argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
