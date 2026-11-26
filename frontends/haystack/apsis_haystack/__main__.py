"""apsis Haystack front-end: emit the apsis IR (JSON) for a built pipeline."""
from __future__ import annotations

from apsis_common.cli import run

from .extract import extract
from .load import get_pipelines


def main(argv: list[str] | None = None) -> int:
    return run(
        prog="apsis_haystack",
        description="emit the apsis IR (JSON) for a built Haystack pipeline",
        spec_help="module:attr | file.py:attr | pipeline.yaml",
        load=get_pipelines,
        extract=extract,
        argv=argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
