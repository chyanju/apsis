# Examples

| folder | what it holds | framework to install |
|---|---|---|
| [running-example/](running-example/) | the running example of the paper: a LangGraph research pipeline whose `verify` step always routes back to `analyze` | `langgraph` |
| [patterns/](patterns/) | one minimal IR for each clause of the paper's pattern catalog | none |

The commands below assume the analyzer is built (`cargo build --release`) and, for a workflow example, that the front-end of its framework is installed next to the framework, for example `pip install langgraph==1.2.6 ./frontends/common ./frontends/langgraph`.

## The running example

```
./target/release/apsis analyze langgraph examples/running-example/graph.py:graph
```

```
apsis · langgraph · bulk-synchronous v1.2.6 · 3 nodes, 4 edges
1 finding
    cycle-termination (closed-cycle) · analyze
        steps ["analyze", "verify"] form a closed cycle: no edge, route or output leads out of it, so it can end only at the engine's iteration limit
```

`graph_fixed.py` is the same pipeline with an exit: `verify` routes to `END` once the analysis is verified. The analyzer reports nothing on it.

## AutoGen issue 960

The paper's example of an over-privileged coordinator, a group chat manager that is given the functions of the assistant, is also a benchmark, so it lives in [`benchmarks/autogen/autogen-960/`](../benchmarks/autogen/autogen-960/). It needs `pyautogen==0.2.32`, which needs Python 3.12 or older.

```
./target/release/apsis analyze autogen benchmarks/autogen/autogen-960/workflow.py:workflow
```

```
apsis · autogen · group chat v0.2.32 · 7 nodes, 9 edges
1 finding
    binding-capability (coordinator-declares-tools) · chat_manager
        coordinator `chat_manager` declares tools, but its role only selects the next speaker and cannot call them
```

Its fixed twin, [`benchmarks/autogen/autogen-960-fixed/`](../benchmarks/autogen/autogen-960-fixed/), gives the manager a config without functions. The analyzer reports nothing on it.

## Patterns

Nineteen IR files, one for each clause of the paper's pattern catalog. They are analyzed directly, without a front-end:

```
./target/release/apsis check examples/patterns/02-runaway-loop.json
```

[patterns/README.md](patterns/README.md) lists the clause each file shows and the rule the analyzer reports on it.
