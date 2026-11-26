<div align="center">
  <img src="docs/logo.png" width="96" alt="Apsis logo">
  <h1>Apsis</h1>
  <p>Static safety analysis for agentic workflows</p>
  <p>
    <a href="https://doi.org/10.5281/zenodo.24408668"><img src="https://img.shields.io/badge/artifact-10.5281%2Fzenodo.24408668-1f6feb" alt="Research artifact: 10.5281/zenodo.24408668"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-6e7781" alt="License: MIT"></a>
  </p>
  <p>
    <a href="#quick-start">Quick start</a> ·
    <a href="docs/detectors.md">Detectors</a> ·
    <a href="benchmarks/README.md">Benchmark suite</a> ·
    <a href="#docker">Docker</a>
  </p>
</div>

Apsis detects workflow bugs, defects in a workflow's wired logic that misroute, stall, or corrupt its actions, without running the workflow. A front-end per framework extracts a built workflow into a language-neutral IR (JSON), and a Rust backend runs the twelve detectors of the paper's catalog over it. Front-ends cover Haystack, LangGraph, AutoGen, Microsoft Agent Framework (its Python and .NET SDKs), Langflow and Flowise.

> [!NOTE]
> Apsis accompanies the paper *Automated Safety Analysis for Agentic Workflows* (ICSE 2027). The research artifact of the paper, version 0.1.0 with the results it reports, is archived at [10.5281/zenodo.24408668](https://doi.org/10.5281/zenodo.24408668).

## Quick start

Build the analyzer, and install the front-ends with the package they share into the Python environment that has the framework:

```
cargo build --release
pip install langgraph==1.2.6 ./frontends/common ./frontends/langgraph ./frontends/langflow
```

Then analyze the running example of the paper, a research pipeline whose `verify` step always routes back to `analyze`:

```
./target/release/apsis analyze langgraph examples/running-example/graph.py:graph
```

```
apsis · langgraph · bulk-synchronous v1.2.6 · 3 nodes, 4 edges
1 finding
    cycle-termination (closed-cycle) · analyze
        steps ["analyze", "verify"] form a closed cycle: no edge, route or output leads out of it, so it can end only at the engine's iteration limit
```

Each finding names the detector, in parentheses the rule of that detector that fired, and the step, socket, edge or channel responsible. The detectors are the twelve of the paper's catalog (β1–β12); a detector covers several failure modes of its bug pattern, one rule each, and [docs/detectors.md](docs/detectors.md) maps them to the paper.

## Usage

`apsis analyze <framework> <source>` extracts a workflow through the front-end of its framework and analyzes it; `apsis check` analyzes an IR file (`-` reads stdin). With the front-ends of the quick start installed, these run as they are:

```
./target/release/apsis analyze langgraph examples/running-example/graph.py:graph --json
./target/release/apsis analyze langflow benchmarks/langflow/langflow-4155/flow.json
./target/release/apsis check examples/patterns/02-runaway-loop.json
```

`--json` prints the report as a JSON document, and `apsis --help` prints the usage. The exit code is 0 without findings, 1 with findings, 2 when the workflow could not be read. A front-end also runs on its own and writes the IR:

```
python3 -m apsis_langgraph graph.py:graph -o ir.json
./target/release/apsis check ir.json
```

## Supported frameworks

| framework | source |
|---|---|
| `haystack` | `file.py:attribute` or `module:attribute` naming a `Pipeline`, or a serialized `pipeline.yaml` |
| `langgraph` | `file.py:attribute` naming a `StateGraph`, compiled or not |
| `autogen` | `file.py:attribute` naming a group chat, a team or a runtime |
| `agent-framework` | `file.py:attribute` naming a `Workflow`, or `project.csproj:Type.Member` for the .NET SDK |
| `langflow` | an exported `flow.json` |
| `flowise` | an exported chatflow or agentflow `flow.json` |

A Python workflow is imported and inspected, never run. Its front-end runs under the `python3` on `PATH`, so run apsis in the environment where the framework and the front-end are installed; a Langflow or Flowise flow needs only its front-end (`pip install ./frontends/common ./frontends/langflow`). A workflow of the .NET SDK is read by the front-end in `frontends/agent-framework-dotnet/`, which apsis runs as `apsis-agent-framework-dotnet` from `PATH`; its [README](frontends/agent-framework-dotnet/README.md) shows how to build it.

## Examples

[examples/README.md](examples/README.md) has the command and the expected report for each example.

| folder | what it holds |
|---|---|
| `examples/running-example/` | the running example of the paper (LangGraph) |
| `examples/patterns/` | one minimal IR for each clause of the paper's pattern catalog |

## Benchmark suite

`benchmarks/` holds the benchmark suite of the paper: 135 benchmarks, each a buggy workflow and its fix. To run the evaluation:

```
cargo build --release
python3 scripts/setup_envs.py
python3 scripts/evaluate.py
```

See [benchmarks/README.md](benchmarks/README.md) for what the script prints and how the benchmarks are organized.

## Docker

The `Dockerfile` builds an image with the analyzer, the environments of the benchmark suite with their front-ends, and the .NET front-end; the container needs no network:

```
docker build -t apsis .
docker run --rm -it --network none apsis
```

In the container, `apsis` is on `PATH` and the environments are set up, so `python3 scripts/evaluate.py` runs directly; `apsis analyze` runs in the environment of the workflow's framework (`. .envs/langgraph/bin/activate`; Langflow and Flowise flows need none).

## Tests

```
cargo test                                         # one test per rule, and the examples in examples/patterns
python3 -m unittest discover -s frontends/tests    # the front-end parts that need no framework
dotnet test frontends/agent-framework-dotnet/tests  # the .NET front-end (needs the .NET SDK 10)
python3 scripts/evaluate.py --check-expected       # every finding, against those recorded with --write-expected
```

## License

MIT, see [LICENSE](LICENSE).
