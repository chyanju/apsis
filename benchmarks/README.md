# Benchmark suite

The benchmark suite of the paper: 135 benchmarks, workflow bugs taken from the issue trackers of six frameworks. Each benchmark is a pair, the **buggy** workflow of the issue and a **fixed** twin, the same workflow after the repair the issue settled on. The analyzer should report the buggy workflow and report nothing on the fixed one.

| framework | benchmarks | workflow artifact | entry | package the front-end needs |
|---|---|---|---|---|
| [haystack](haystack/) | 25 | `pipeline.py` | `pipeline.py:pipeline` | `haystack-ai` |
| [langgraph](langgraph/) | 33 | `graph.py` | `graph.py:graph` | `langgraph` |
| [flowise](flowise/) | 24 | `flow.json` | `flow.json` | none |
| [langflow](langflow/) | 13 | `flow.json` | `flow.json` | none |
| [autogen](autogen/) | 14 | `workflow.py` | `workflow.py:workflow` | `pyautogen` (0.2 API) or `autogen-agentchat` (0.4 API) |
| [agent-framework](agent-framework/) | 26 | `workflow.py` (8), a C# project (18) | `workflow.py:workflow`, `Workflow.csproj:<namespace>.Case.Build` | `agent-framework-core`; the .NET SDK 10 |
| **total** | **135** | | | |

`suite.json` lists the benchmarks with their fixed twin and the bug category the paper files them under. Each benchmark's `meta.json` gives its issue and describes the bug and the fix.

## Running the evaluation

```
cargo build --release
python3 scripts/setup_envs.py        # once: creates .envs/ from environments.json (the C# benchmarks need the .NET SDK 10)
python3 scripts/evaluate.py
```

`scripts/evaluate.py` runs every artifact of the benchmark suite through its front-end and `apsis check`, then prints the per-framework table (Table 4 of the paper), the per-category table (the Apsis rows of Table 5) and the recall with and without the behavioral detectors (Fig. 8). A buggy artifact with at least one finding counts as detected; a fixed twin with at least one finding counts as a false positive.

- `--check` compares every count with the numbers the paper reports and fails if one is worse. Those numbers are `benchmarks/paper-results.json` of the paper's artifact (https://doi.org/10.5281/zenodo.24408668); copy that file here, or name it with `--paper`.
- `--write-expected` records the findings of every artifact, each as `detector/rule@location`, in `benchmarks/expected-findings.json`, and `--check-expected` fails if a later run differs from them.
- `--by-detector` adds a table of how many buggy artifacts and fixed twins each of the twelve detectors, and each of its rules, fires on.
- `environments.json` lists the Python environments the front-ends run in and which artifact uses which.
- The last line of the output is the time per artifact, front-end plus analysis. The paper's analysis time is that line for a sequential run, `--jobs 1`, on a 4-core Arm Neoverse-N1 machine; with parallel jobs the artifacts compete for the cores and each takes longer.

## Layout

```
benchmarks/
  suite.json                      # the 135 benchmarks, their fixed twins and categories
  environments.json               # the Python environments the front-ends run in
  environments/<name>.txt         # every package of each environment, with its version
benchmarks/<framework>/
  <framework>-<issue>/            # the buggy workflow: the artifact and meta.json, with requirements.txt for a
                                  # Python or Langflow benchmark (a C# benchmark: Workflow.csproj, Workflow.cs, Run.cs)
  <framework>-<issue>-fixed/      # its fixed twin
```

A fixed twin is named `-fixed0` when the issue was repaired both in the workflow and in the framework; the twin is the workflow repair. When the repair needs the framework change, the twin keeps the name `-fixed` and is built on the changed component (langflow-11234).

## The artifacts

A Python benchmark (`pipeline.py`, `graph.py`, `workflow.py`) builds the workflow of the issue with the framework's public API. The module constructs the workflow object when it is imported and never runs it: no `run()` or `invoke()`, no network access, no API key. The bodies of nodes and agents are stubs; what the benchmark carries is the structure the issue is about (routers, loops, sub-workflows, fan-in, tool and handoff bindings, channels, message types). A front-end imports the module and reads the object.

A visual-builder benchmark (`flow.json`) is a flow in the framework's export format, written by hand and reduced to the nodes, handles and edges the issue involves; flowise-3929 and its twin are built from the export attached to the issue. For these frameworks the exported graph is the program, so the front-end parses it directly.

Eighteen of the Agent Framework benchmarks, from issues reported against the .NET SDK, are C# projects; agent-framework-2163, whose issue was also reported against the .NET SDK, is written with the Python SDK. In a C# benchmark `Workflow.csproj` pins the `Microsoft.Agents.AI.Workflows` release of the issue (and `OpenTelemetry.Api` 1.15.3, since the 1.13.1 those packages resolve has CVE-2026-40894), `Workflow.cs` holds the workflow (`Case.Build()` constructs it and does not run it) and `Run.cs` runs it once offline, so `dotnet run` shows the failure the issue reports. Agents use a chat client that answers with fixed text. The front-end in `frontends/agent-framework-dotnet/` builds the project and reads the built workflow.

`framework_version` records the framework release of a benchmark; `requirements.txt` (for a C# benchmark, `Workflow.csproj`) pins it. The evaluation runs the Python benchmarks of a framework in one environment, in which all of them load; `environments.json` lists the environments and the benchmarks that run under a release of their own. A C# benchmark runs under the release its project pins.

## meta.json

```json
{
  "id": "langgraph-1406",
  "issue_url": "https://github.com/langchain-ai/langgraph/issues/1406",
  "fix_kind": "workflow",
  "framework_version": "1.2.6",
  "entry": "graph.py:graph",
  "expected_detectors": ["channel-write-merge"],
  "note": "what is wrong in the buggy workflow and how the fix removes it"
}
```

- `entry` is what the front-end is given: a file, or `file:attribute` for a Python module.
- `fix_kind` is `workflow` when the issue was repaired by changing the workflow, `mixed` when it was also repaired in the framework. In a fixed twin it is the kind of the twin's own repair: `workflow` for a `-fixed0` twin.
- `expected_detectors` is the detector whose pattern the benchmark is labelled with; a fixed twin has `[]`. The evaluation counts a benchmark as detected when any detector reports it, whatever the label.
- `framework_version` is the framework release of the benchmark.
- A fixed twin's meta names its benchmark in `of` and describes the repair in `fix_note`.
