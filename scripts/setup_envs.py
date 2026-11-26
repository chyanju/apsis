#!/usr/bin/env python3
"""Create the environments the front-ends need to analyze the benchmark suite and the bugs.

    python3 scripts/setup_envs.py                 # all environments
    python3 scripts/setup_envs.py langgraph       # only the named ones

An environment with a lock file, environments/<name>.txt next to the environments.json that lists it, gets
exactly the packages it pins.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUITES = ("benchmarks", "bugs")  # each lists environments in environments.json, with lock files in environments/
FRAMEWORKS = ("agent-framework", "autogen", "crewai", "haystack", "langgraph", "llamaindex", "parlant", "pydantic-ai")  # the front-ends an environment can serve


def normalized(package):
    return re.sub(r"[-_.]+", "-", package).lower()


def install_command(python, name, entry):
    """The pip command of an environment, from its lock file if it has one; (None, reason) if the lock disagrees."""
    pip = [python, "-m", "pip", "install", "--quiet", "--disable-pip-version-check"]
    lock = next((p for p in (os.path.join(REPO, suite, "environments", name + ".txt") for suite in SUITES)
                 if os.path.exists(p)), None)
    if lock is None:
        return pip + entry["requirements"], None
    pins = {}
    with open(lock, encoding="utf-8") as f:
        for line in f:
            if "==" in line:
                package, version = line.strip().split("==", 1)
                pins[normalized(package)] = version
    for req in entry["requirements"]:
        package, version = req.split("==", 1)
        if pins.get(normalized(package.split("[")[0])) != version:
            return None, f"{os.path.relpath(lock, REPO)} does not pin {req}"
    sdists = entry.get("sdists", [])  # packages that publish no wheel, built from their source release
    return pip + ["--no-deps", "--only-binary=:all:"] + ([f"--no-binary={','.join(sdists)}"] if sdists else []) + ["-r", lock], None


def link_frontends(target, name):
    """Make the environment import its framework's front-end from frontends/ (a .pth file with the two paths)."""
    framework = next((f for f in FRAMEWORKS if name == f or name.startswith(f + "-")), None)
    if framework is None:
        return
    site = subprocess.run([os.path.join(target, "bin", "python"), "-c",
                           "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                          capture_output=True, text=True).stdout.strip()
    with open(os.path.join(site, "apsis-frontends.pth"), "w", encoding="utf-8") as f:
        f.write(f"{os.path.join(REPO, 'frontends', 'common')}\n{os.path.join(REPO, 'frontends', framework)}\n")


def version_of(python):
    out = subprocess.run([python, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None
    major, minor = out.stdout.split()
    return int(major), int(minor)


def interpreter_below(limit, preferred):
    """An interpreter older than `limit` (a (major, minor) pair): `preferred` if it qualifies, else one on PATH."""
    candidates = [preferred] + [f"python{limit[0]}.{m}" for m in range(limit[1] - 1, 8, -1)]
    for cand in candidates:
        path = cand if os.path.isabs(cand) else shutil.which(cand)
        if path:
            v = version_of(path)
            if v and v < limit:
                return path
    return None


def setup_dotnet(target_dir):
    """Publish the .NET front-end and build every C# artifact once, which restores its packages."""
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        print("dotnet: the .NET SDK is not on PATH; install the .NET SDK 10")
        return False
    version = subprocess.run([dotnet, "--version"], capture_output=True, text=True).stdout.strip()
    if not version or int(version.split(".")[0]) < 10:
        print(f"dotnet: needs the .NET SDK 10 or newer, found {version or 'none'}")
        return False
    build = os.path.join(target_dir, "dotnet", "build")
    projects = sorted(glob.glob(os.path.join(REPO, "benchmarks", "*", "*", "*.csproj")))
    print(f"dotnet: the .NET front-end and {len(projects)} C# artifacts (SDK {version})", flush=True)
    # ReadyToRun precompiles the front-end and Roslyn, which halves the time a run takes
    steps = [[dotnet, "publish", os.path.join(REPO, "frontends", "agent-framework-dotnet", "src"), "-c", "Release",
              "--use-current-runtime", "--self-contained", "false", "-p:PublishReadyToRun=true",
              "-o", os.path.join(target_dir, "dotnet", "frontend"), "--artifacts-path", os.path.join(build, "frontend")]]
    # scripts/evaluate.py builds in the same directories, so its builds are incremental
    steps += [[dotnet, "build", p, "-c", "Release", "--artifacts-path", os.path.join(build, os.path.basename(os.path.dirname(p)))]
              for p in projects]
    for cmd in steps:
        done = subprocess.run(cmd + ["--nologo", "-v", "quiet"], capture_output=True, text=True)
        if done.returncode != 0:
            print(f"  failed: {' '.join(cmd)}\n  {(done.stdout + done.stderr).strip()[-600:]}")
            return False
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", help="environments to create (default: all)")
    ap.add_argument("--dir", default=os.path.join(REPO, ".envs"), help="where to create them (default: .envs)")
    ap.add_argument("--python", default=sys.executable, help="interpreter for the environments (default: this one)")
    ap.add_argument("--with-frontends", action="store_true",
                    help="let each environment import its framework's front-end, so `apsis analyze` runs in it")
    args = ap.parse_args()

    spec = {}
    for suite in SUITES:
        path = os.path.join(REPO, suite, "environments.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                spec.update(json.load(f)["environments"])
    known = sorted(spec) + ["dotnet"]
    unknown = [n for n in args.names if n not in known]
    if unknown:
        sys.exit(f"unknown environment(s) {unknown}; known: {known}")
    default = sorted(spec) + (["dotnet"] if glob.glob(os.path.join(REPO, "benchmarks", "*", "*", "*.csproj")) else [])
    os.makedirs(args.dir, exist_ok=True)
    failed = []
    for name in args.names or default:
        if name == "dotnet":
            if not setup_dotnet(args.dir):
                failed.append(name)
            continue
        entry = spec[name]
        python = args.python
        if "python_below" in entry:
            limit = tuple(int(x) for x in entry["python_below"].split("."))
            python = interpreter_below(limit, args.python)
            if python is None:
                print(f"{name}: needs Python older than {entry['python_below']}; none found (pass --python)")
                failed.append(name)
                continue
        target = os.path.join(args.dir, name)
        install, problem = install_command(os.path.join(target, "bin", "python"), name, entry)
        if problem:
            print(f"{name}: {problem}")
            failed.append(name)
            continue
        print(f"{name}: {' '.join(entry['requirements'])}  (python {'.'.join(map(str, version_of(python)))})", flush=True)
        for cmd in ([python, "-m", "venv", target], install):
            done = subprocess.run(cmd, capture_output=True, text=True)
            if done.returncode != 0:
                print(f"  failed: {' '.join(cmd)}\n  {(done.stderr or done.stdout).strip()[-600:]}")
                failed.append(name)
                break
        else:
            if args.with_frontends:
                link_frontends(target, name)
    if failed:
        sys.exit(f"could not create: {', '.join(failed)}")
    print(f"environments are in {args.dir}")


if __name__ == "__main__":
    main()
