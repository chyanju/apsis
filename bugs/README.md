# Bugs

Bugs that Apsis found in open-source projects and that were reported to them. A folder holds one bug: the workflow of the project at a commit that has the bug, taken out of the project into a module that loads with the framework alone. The number that opens a folder's name is the row of the bug in the paper's table of bugs.

The analyzer should report the bug on the workflow. Where the project repaired the workflow, the folder also holds a **fixed reference**, the same workflow after that repair, on which the findings of the bug should be gone; other findings may remain on it.

## Running the check

```
cargo build --release
python3 scripts/setup_envs.py        # once: creates .envs/, with the environments of bugs/environments.json
python3 scripts/check_bugs.py
```

`scripts/check_bugs.py` runs every bug through its front-end and `apsis check`. For each bug it prints whether the findings that expose it are reported, how many other findings the workflow has, and what is reported on the fixed reference. It fails when a bug is not reported. `--list` prints the findings, and a folder name as argument selects a bug.

## Layout

```
bugs/
  environments.json              # the environments the bugs need beyond those of the benchmark suite
  environments/<name>.txt        # every package of each of them, with its version
bugs/<number>-<project>-<issue>/
  meta.json                      # the issue, the source in the project, the findings that expose the bug
  graph.py                       # the workflow with the bug
  requirements.txt               # the release it loads under
  fixed/graph.py                 # the fixed reference
  LICENSE                        # the license of the project, for a workflow that copies its code
```

A workflow module builds the workflow when it is imported and never runs it. The state schema, the routing functions and the wiring are the project's; a node body keeps the state it reads and writes and the targets it routes to, with calls to models, tools and services replaced by constants. Where the project runs its steps in plain code rather than as a workflow object, the module writes them as a workflow of the framework, and the note in meta.json says so. A module that copies code from its project says so in its first lines and keeps the notice of the file it copies; the folder then holds the project's license as `LICENSE`, which `license` in meta.json names. For a project without a license, or under a copyleft one, the module is written after the project's workflow and copies none of its code, and meta.json has no `license`.

Two bugs of one workflow share its module: the `entry` of the second names the file in the folder of the first, or the module of the second loads it. A bug repaired in the framework has no second module; its fixed reference is the same `entry` in an environment with the repaired release.

## meta.json

```json
{
  "id": "25-openagent-248",
  "issue_url": "https://github.com/Haohao-end/openagent/issues/248",
  "source": ["https://github.com/Haohao-end/openagent/blob/<commit>/api/internal/core/workflow/workflow.py"],
  "license": "MIT",
  "framework": "langgraph",
  "entry": "graph.py:graph",
  "expected_findings": ["target-resolution/label-outside-path-map@<step>:false"],
  "note": "what is wrong in the workflow",
  "fixed": {
    "entry": "fixed/graph.py:graph",
    "fix_url": "https://github.com/Haohao-end/openagent/pull/264",
    "fix_note": "what the repair changes"
  }
}
```

- `source` lists the files of the project the workflow is taken from, at the commit it is taken from.
- `framework` selects the front-end, and `entry` is what the front-end is given, relative to the folder.
- `expected_findings` are the findings that expose the bug, each as `detector/rule@location`. The bug counts as reported when all of them are.
- `environment` names the Python environment when it is not the default of the framework in `benchmarks/environments.json`; `fixed` can name its own.
- `fixed` is absent when the project left the workflow as it is.
