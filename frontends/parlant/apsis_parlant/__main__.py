"""apsis parlant front-end: emit the apsis IR (JSON) for parlant journeys."""
from __future__ import annotations

from apsis_common.cli import run

from .extract import extract
from .load import get_journeys


def main(argv: list[str] | None = None) -> int:
    return run(
        prog="apsis_parlant",
        description="emit the apsis IR (JSON) for parlant journeys, as JourneyStore lists them",
        spec_help="module:attr | file.py:attr",
        load=get_journeys,
        extract=extract,
        suppress_stdout=True,
        argv=argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
