<div align="center">

<img src="docs/logo.png" alt="apsis logo" width="100" />

# apsis

**Artifact of the ICSE 2027 paper *Automated Safety Analysis for Agentic Workflows***

</div>

---

## Purpose

Apsis is a static safety analyzer for agentic workflows. It detects workflow bugs, defects in a workflow's wired logic that misroute, stall, or corrupt its actions, without running the workflow. A per-framework front-end extracts a built workflow into a language-neutral IR (JSON), and a Rust backend runs the twelve detectors of the paper's catalog (β1–β12) over the IR. A detector covers several failure modes of its bug pattern, one rule each; [docs/detectors.md](docs/detectors.md) maps them to the paper.

The artifact reproduces the results of RQ1 and RQ2:

| result in the paper | command |
|---|---|
| Table 4 (detection per framework), the Apsis rows of Table 5 (per bug category), Fig. 8 (recall without and with the behavioral detectors) | `python3 scripts/evaluate.py --check` |
| the analysis time per workflow (RQ1) | `python3 scripts/evaluate.py --jobs 1` |
| the Framework-Native Validator row of Table 5 | `python3 baselines/native-validator/run.py` |
| the CodeQL and LLM rows of Table 5 | `python3 baselines/codeql/score.py`, `python3 baselines/llm/score.py` |

| folder | contents |
|---|---|
| `crates/` | the analyzer: IR, detectors, command line (Rust) |
| `frontends/` | the front-ends for Haystack, LangGraph, AutoGen, Microsoft Agent Framework (its Python and .NET SDKs), Langflow and Flowise |
| `benchmarks/` | the paper's benchmark suite (135 benchmarks), the numbers the paper reports on it, and the findings on every artifact |
| `baselines/` | the baselines of Table 5, with the CodeQL and LLM runs the paper reports |
| `examples/` | the paper's running example and one minimal IR per clause of its pattern catalog |
| `scripts/` | the setup of the evaluation environments, and the evaluation |

## Badges claimed

**Available.** The artifact is archived on Zenodo with a DOI (see Provenance), under the MIT license.

**Reusable.**
- Apsis is a general analyzer: `apsis analyze <framework> <source>` analyzes workflows built with the six frameworks, not only those of the benchmark suite, and `apsis check` analyzes any IR file, so a further framework needs only a front-end that writes the IR.
- The benchmark suite serves other tools: each benchmark is a buggy workflow and its fixed twin, with a `meta.json` that gives the issue, the framework release, the entry point, and what the bug and the fix are. The C# benchmarks run with `dotnet run` and show the failure of their issue. The baselines of Table 5 run on the same files.
- Every rule has a unit test, the front-ends have tests, and `scripts/evaluate.py --check-expected` compares every finding on the 270 artifacts with the recorded ones.
- The image pins the toolchains and, through the lock files in `benchmarks/environments/`, every Python package; it runs without network access.

## Provenance

This artifact, version 0.1.0, is archived at https://doi.org/10.5281/zenodo.24408668. The record holds this source (`apsis-0.1.0.zip`), the built Docker image for x86-64 and for Arm (`apsis-0.1.0-amd64.tar.gz`, `apsis-0.1.0-arm64.tar.gz`), the paper in its extended version with the link to the archive (`paper.pdf`), and the two-page artifact abstract (`abstract.pdf`).

## Data

`benchmarks/` holds the benchmark suite, 135 workflow bugs reported in the public issue trackers of the six frameworks. Each benchmark is a minimal workflow that reproduces its issue, paired with its fixed twin: 270 artifacts (Python modules, exported Langflow and Flowise flows, C# projects) in 798 files, 1.2 MB. A benchmark's `meta.json` links its issue; the benchmarks hold no personal data. [benchmarks/README.md](benchmarks/README.md) describes the benchmarks, their metadata and the environments they run in.

## Setup

Hardware: an x86-64 or Arm (aarch64) machine. The evaluation uses under 1 GB of memory, and the image with its base images takes about 8 GB of disk. No GPU. Tested on a 4-core x86-64 machine (AMD EPYC) with 16 GB of memory and on a 4-core Arm machine (Neoverse-N1) with 24 GB.

Software: Docker (tested with 29.1). Load the built image for your machine from the Zenodo record, or build it from this directory, which takes about 15 minutes and downloads the base images and the pinned packages:

```
docker load -i apsis-0.1.0-amd64.tar.gz     # on Arm: apsis-0.1.0-arm64.tar.gz
docker build -t apsis .                      # instead of loading it
```

Then start a shell in it; the container needs no network:

```
docker run --rm -it --network none apsis
```

The image holds the analyzer (`apsis` on `PATH`), the Python environments of the evaluation in `.envs/`, the .NET SDK and the .NET front-end. The commands below run in the container's shell, in `/apsis`.

Without Docker, the Dockerfile's steps run on a machine with Rust, Python 3.13 and 3.12, and the .NET SDK 10.

## Usage

### Basic test (one minute)

```
apsis check examples/patterns/02-runaway-loop.json
. .envs/langgraph/bin/activate
apsis analyze langgraph examples/running-example/graph.py:graph
deactivate
```

The third command analyzes the running example of the paper, a LangGraph research pipeline whose `verify` step always routes back to `analyze`, and prints:

```
apsis · langgraph · bulk-synchronous v1.2.6 · 3 nodes, 4 edges
1 finding
    cycle-termination (closed-cycle) · analyze
        steps ["analyze", "verify"] form a closed cycle: no edge, route or output leads out of it, so it can end only at the engine's iteration limit
```

A finding names the detector, in parentheses the rule that fired, and the step, socket, edge or channel responsible. [examples/README.md](examples/README.md) lists further examples with their reports.

### Reproducing the results (two minutes)

```
python3 scripts/evaluate.py --check --check-expected
```

The script runs the front-end and the analyzer on all 270 artifacts and prints Table 4, the Apsis rows of Table 5 and the recall of Fig. 8. It then compares every finding with `benchmarks/expected-findings.json` and every number with the paper's, `benchmarks/paper-results.json`, and ends with:

```
Findings match expected-findings.json on every artifact.

Compared with the paper (benchmarks/paper-results.json):
  every number is identical
```

The analysis time of RQ1, 0.7 s median and 0.8 s mean per workflow, is the timing line of a sequential run, `python3 scripts/evaluate.py --jobs 1` (four minutes); it depends on the machine.

### Baselines (Table 5)

```
python3 baselines/native-validator/run.py
python3 baselines/codeql/score.py
python3 baselines/llm/score.py
```

The native validator (two minutes) builds every workflow with its framework's own construction-time checks and ends with `135 benchmarks: P ---, R 0.00, F1 ---, FPR 0.00`. The CodeQL and LLM scripts score the runs the paper reports and print its rows. Running CodeQL again needs the CodeQL bundle for Linux x86-64 or macOS, and running an LLM judge calls the provider's API with your key and is billed; [baselines/codeql/README.md](baselines/codeql/README.md) and [baselines/llm/README.md](baselines/llm/README.md) give the commands.

### Tests

```
python3 -m unittest discover -s frontends/tests
dotnet test frontends/agent-framework-dotnet/tests
```

The Rust tests (`cargo test`, one test per rule) run while the image is built.

### Analyzing other workflows

`apsis analyze <framework> <source> [--json]` analyzes a workflow, and `apsis check <ir.json>` an IR file that a front-end wrote. A Python workflow is imported and inspected, never run, by the front-end of its framework, which runs under the `python3` on `PATH`, so activate the framework's environment in `.envs/` first (`benchmarks/environments.json` lists the release each one holds). Langflow and Flowise flows need no environment, and a .NET project is read by the .NET front-end.

| framework | source |
|---|---|
| `haystack` | `file.py:attribute` or `module:attribute` naming a `Pipeline`, or a serialized `pipeline.yaml` |
| `langgraph` | `file.py:attribute` naming a `StateGraph`, compiled or not |
| `autogen` | `file.py:attribute` naming a group chat, a team or a runtime |
| `agent-framework` | `file.py:attribute` naming a `Workflow`, or `project.csproj:Type.Member` for the .NET SDK |
| `langflow` | an exported `flow.json` |
| `flowise` | an exported chatflow or agentflow `flow.json` |

`--json` prints the report as a JSON document. The exit code is 0 without findings, 1 with findings, and 2 when the workflow could not be read.

## License

MIT, see [LICENSE](LICENSE).
