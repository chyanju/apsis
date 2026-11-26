"""apsis CrewAI front-end: emit the apsis IR (JSON) for built crews."""
from __future__ import annotations

from apsis_common.cli import run

from .extract import extract
from .load import get_crews


def main(argv: list[str] | None = None) -> int:
    return run(
        prog="apsis_crewai",
        description="emit the apsis IR (JSON) for a CrewAI crew, or a list of crews",
        spec_help="module:attr | file.py:attr",
        load=get_crews,
        extract=extract,
        suppress_stdout=True,
        argv=argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
