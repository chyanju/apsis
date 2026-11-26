"""apsis PydanticAI front-end: emit the apsis IR (JSON) for agents and the runs their tools start."""
from __future__ import annotations

from apsis_common.cli import run

from .extract import extract
from .load import get_runs


def main(argv: list[str] | None = None) -> int:
    return run(
        prog="apsis_pydantic_ai",
        description="emit the apsis IR (JSON) for a PydanticAI agent with the deps of a run, or a list of them",
        spec_help="module:attr | file.py:attr",
        load=get_runs,
        extract=extract,
        suppress_stdout=True,
        argv=argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
