# Artifact for "Automated Safety Analysis for Agentic Workflows"

ICSE 2027, Research Track

## The artifact

Apsis is a static safety analyzer for agentic workflows. It detects workflow bugs, defects in a workflow's wired logic that misroute, stall, or corrupt its actions, without running the workflow. The artifact contains:

- the analyzer (Rust) and its front-ends for six agent-workflow frameworks: Haystack, LangGraph, AutoGen, Microsoft Agent Framework (its Python and .NET SDKs), Langflow and Flowise;
- the paper's benchmark suite: 135 workflow bugs from the frameworks' public issue trackers, each benchmark a minimal buggy workflow paired with its fixed twin;
- the baselines of the paper's Table 5 (the frameworks' native validators, CodeQL, three LLM judges), with the CodeQL and LLM runs the paper reports;
- the scripts that reproduce the results of RQ1 and RQ2: Table 4, Table 5, Fig. 8 and the analysis time;
- a Docker image with everything installed, and the Dockerfile that builds it.

## Badges claimed

- **Available**: archived on Zenodo with a DOI, under the MIT license.
- **Reusable**: Apsis analyzes workflows of the six frameworks beyond the benchmark suite, through a documented command line and a language-neutral IR that further front-ends can target. The suite comes with metadata for every benchmark (issue, framework release, entry point, bug and fix), and its C# benchmarks run and show the failure of their issue. Every rule has a unit test, and a regression check compares every finding on the suite's 270 artifacts with the recorded ones. The image pins the toolchains and every Python package, and runs offline.

## Reviewer skills

A Unix shell and Docker. Reading Python helps to inspect the benchmarks; running the artifact needs no knowledge of Rust, C# or the frameworks.

## Access

The artifact is archived at https://doi.org/10.5281/zenodo.24408668. The record holds the source (`apsis-0.1.0.zip`, whose `README.md` describes setup and usage), the built Docker image for x86-64 and for Arm (`apsis-0.1.0-amd64.tar.gz`, `apsis-0.1.0-arm64.tar.gz`) and the paper.

1. `docker load -i apsis-0.1.0-amd64.tar.gz` loads the image (on Arm, the `arm64` file); alternatively, `docker build -t apsis .` in the unpacked source builds it in about 15 minutes, with network access.
2. `docker run --rm -it --network none apsis` opens a shell in it.
3. The basic test takes a minute; `python3 scripts/evaluate.py --check --check-expected` reproduces Table 4, the Apsis rows of Table 5 and Fig. 8 in two minutes and checks every number against the paper; the scripts in `baselines/` print the other rows of Table 5.

## Runtime requirements

- An x86-64 or Arm (aarch64) machine with Docker. The evaluation uses under 1 GB of memory. Tested on 4-core x86-64 and Arm machines with 16 GB and 24 GB of memory.
- About 8 GB of disk. No GPU.
- The loaded image runs without network access; building it downloads the base images and the pinned packages. Re-running the CodeQL baseline needs the CodeQL bundle for Linux x86-64 or macOS, and re-running the LLM judges needs the providers' API keys and is billed; both are optional, since the runs the paper reports are scored offline.
