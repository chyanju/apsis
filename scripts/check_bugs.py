#!/usr/bin/env python3
"""Run Apsis on the bugs in bugs/ and print, per bug, whether the findings that expose it are reported, the
other findings of its workflow, and what is reported on its fixed reference.

    cargo build --release
    python3 scripts/setup_envs.py          # once: creates .envs/<environment>
    python3 scripts/check_bugs.py
"""
from __future__ import annotations

import argparse
import concurrent.futures
import glob
import os
import shutil
import sys

from evaluate import REPO, Runner, load_json

BUGS = os.path.join(REPO, "bugs")


def interpreter(runner, framework, environment):
    """The Python interpreter a front-end runs under: the named environment, or the default of the framework."""
    env = environment or runner.envs["framework_default"][framework]
    if env is None:
        return sys.executable  # a flow.json front-end: no framework needed
    python = os.path.join(runner.envs_dir, env, "bin", "python")
    if not os.path.exists(python):
        raise FileNotFoundError(f"environment '{env}' not found at {python}; run scripts/setup_envs.py")
    return python


def analyze(runner, meta, name, entry, environment):
    """The findings of one entry of a bug, each as `detector/rule@location`, or {'error': ...}."""
    source = os.path.normpath(os.path.join(BUGS, meta["id"], entry))
    try:
        python = None if ".csproj:" in entry else interpreter(runner, meta["framework"], environment)
    except (OSError, KeyError) as e:
        return {"error": str(e)}
    result = runner.analyze(meta["framework"], name, source, python)
    if "error" in result:
        return result
    return {"findings": [f"{d}/{rule}@{loc}" for d, rule, loc in result["findings"]]}


def check(runner, meta):
    """Analyze a bug and its fixed reference."""
    out = {"bug": analyze(runner, meta, meta["id"], meta["entry"], meta.get("environment"))}
    fixed = meta.get("fixed")
    if fixed:
        out["fixed"] = analyze(runner, meta, meta["id"] + "-fixed", fixed["entry"],
                               fixed.get("environment", meta.get("environment")))
    return out


def plural(n, noun):
    return f"{n} {noun}{'' if n == 1 else 's'}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", help="bugs to check, by folder name (default: all)")
    ap.add_argument("--envs", default=os.path.join(REPO, ".envs"), help="directory holding the environments (default: .envs)")
    ap.add_argument("--apsis", default=os.path.join(REPO, "target", "release", "apsis"), help="the analyzer binary")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--keep", metavar="DIR", help="keep the IR files and front-end stderr in DIR")
    ap.add_argument("--list", action="store_true", help="print the findings; `*` marks those that expose the bug")
    args = ap.parse_args()

    if not os.path.exists(args.apsis):
        sys.exit(f"analyzer not found at {args.apsis}; run `cargo build --release` or pass --apsis")
    metas = [load_json(p) for p in sorted(glob.glob(os.path.join(BUGS, "*", "meta.json")))]
    unknown = sorted(set(args.names) - {m["id"] for m in metas})
    if unknown:
        sys.exit(f"unknown bug(s) {unknown}")
    if args.names:
        metas = [m for m in metas if m["id"] in args.names]
    runner = Runner(argparse.Namespace(tree=REPO, apsis=args.apsis, envs=args.envs, dotnet_frontend=None, keep=args.keep))
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        results = list(pool.map(lambda m: check(runner, m), metas))

    width = max(len(m["id"]) for m in metas)
    print(f"{'bug':{width}s}  reported  other findings  fixed reference")
    reported = references = gone = clean = 0
    failed = False
    for meta, res in zip(metas, results):
        expected = meta["expected_findings"]
        bug, fixed = res["bug"], res.get("fixed")
        if "error" in bug:
            failed = True
            print(f"{meta['id']:{width}s}  error: {bug['error']}")
            continue
        missing = [f for f in expected if f not in bug["findings"]]
        reported += not missing
        failed = failed or bool(missing)
        if fixed is None:
            note = "none"
        elif "error" in fixed:
            failed = True
            note = "error: " + fixed["error"]
        else:
            references += 1
            left = [f for f in expected if f in fixed["findings"]]
            others = len(fixed["findings"]) - len(left)
            gone += not left
            clean += not fixed["findings"]
            note = ("still reported" if left else "no findings" if not others else "bug gone") + (
                f", {plural(others, 'other finding')}" if others else "")
        others = len([f for f in bug["findings"] if f not in expected])
        print(f"{meta['id']:{width}s}  {'no' if missing else 'yes':8s}  {others:14d}  {note}")
        if args.list:
            for f in bug["findings"]:
                print(f"    {'*' if f in expected else ' '} {f}")
            for f in missing:
                print(f"    missing: {f}")
            if fixed and fixed.get("findings"):
                print("    on the fixed reference:")
                for f in fixed["findings"]:
                    print(f"    {'*' if f in expected else ' '} {f}")
    print(f"\n{reported} of {plural(len(metas), 'bug')} reported; {plural(references, 'fixed reference')}: "
          f"the bug is gone on {gone}, no findings on {clean}")
    if args.keep is None:
        shutil.rmtree(runner.workdir, ignore_errors=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
