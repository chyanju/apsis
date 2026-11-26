# Agent Framework front-end for the .NET SDK

Reads a workflow written against the .NET SDK of Microsoft Agent Framework (`Microsoft.Agents.AI.Workflows`) and writes the apsis IR as JSON. The workflow's project is built, and its `Workflow` object is constructed and inspected; the workflow is never run. It needs the .NET SDK 10.

```
dotnet publish frontends/agent-framework-dotnet/src -c Release --use-current-runtime --self-contained false \
    -p:PublishReadyToRun=true -o <dir>
<dir>/apsis-agent-framework-dotnet <project.csproj>:<Type.Member> [-o ir.json] [--artifacts DIR]
```

ReadyToRun precompiles the front-end and Roslyn for the machine, which halves the time of a run; a plain `dotnet build frontends/agent-framework-dotnet/src -c Release` works too. `python3 scripts/setup_envs.py dotnet` publishes it this way into `.envs/dotnet/frontend`.

`Type.Member` is a static property, field or parameterless method of the project that returns the built `Workflow`; a `WorkflowBuilder` is built. The project is built with `dotnet build` into a temporary directory, so nothing is written next to it, and loaded with the package versions it references, so one front-end reads workflows of different SDK releases. `--artifacts DIR` builds into `DIR` and keeps it, so the next run builds incrementally. The source is read with the files and references the build gave the compiler.

`apsis analyze agent-framework <project.csproj>:<Type.Member>` runs this front-end as `apsis-agent-framework-dotnet` from `PATH`, so add `<dir>` to `PATH`.

Tests: `dotnet test frontends/agent-framework-dotnet/tests`.
