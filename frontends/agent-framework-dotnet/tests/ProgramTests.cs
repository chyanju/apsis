using System.Runtime.CompilerServices;
using System.Text.Json.Nodes;
using Microsoft.Agents.AI.Workflows;
using Xunit;

namespace Apsis.AgentFramework.Dotnet.Tests;

internal static class Scopes
{
    public const string Shared = "Shared";
}

internal sealed class Writer() : Executor<string, string>("writer")
{
    public override async ValueTask<string> HandleAsync(string message, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        string key = Guid.NewGuid().ToString();
        await context.QueueStateUpdateAsync(key, message, scopeName: Scopes.Shared, cancellationToken);
        await context.QueueStateUpdateAsync("count", 1, cancellationToken: cancellationToken);
        return key;
    }
}

internal sealed class Reader() : Executor<string, string>("reader")
{
    public override async ValueTask<string> HandleAsync(string key, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        string? text = await context.ReadStateAsync<string>(key, scopeName: Scopes.Shared, cancellationToken);
        _ = await context.ReadStateAsync<int>("seen", cancellationToken: cancellationToken);
        return text ?? "";
    }
}

internal sealed class Answerer() : Executor<ExternalRequest>("answerer")
{
    public override ValueTask HandleAsync(ExternalRequest message, IWorkflowContext context, CancellationToken cancellationToken = default)
        => context.SendMessageAsync(message.CreateResponse("yes"), cancellationToken: cancellationToken);
}

public class ProgramTests
{
    private static string ThisFile([CallerFilePath] string path = "") => path;

    /// The global usings a build generates for `ImplicitUsings`.
    private const string ImplicitUsings = """
        global using System;
        global using System.Collections.Generic;
        global using System.IO;
        global using System.Linq;
        global using System.Net.Http;
        global using System.Threading;
        global using System.Threading.Tasks;
        """;

    private static SourceFacts Facts() => SourceFacts.FromSources(
        [(ThisFile(), File.ReadAllText(ThisFile())), ("GlobalUsings.cs", ImplicitUsings)],
        Directory.EnumerateFiles(AppContext.BaseDirectory, "*.dll").Where(f => !f.EndsWith("Apsis.AgentFramework.Dotnet.Tests.dll", StringComparison.Ordinal)));

    private static JsonArray Workflows(Workflow workflow, SourceFacts? facts = null) =>
        Extractor.Program(workflow, facts ?? new SourceFacts(), "test")["workflows"]!.AsArray();

    private static JsonObject NodeOf(JsonNode wf, string id) =>
        (JsonObject)wf["nodes"]!.AsArray().Single(n => (string)n!["id"]! == id)!;

    private static Workflow Approval()
    {
        var start = new Echo("sub_start");
        RequestPort<string, string> ask = RequestPort.Create<string, string>("ask");
        var after = new Echo("sub_after");
        return new WorkflowBuilder(start).AddEdge(start, ask).AddEdge(ask, after).WithOutputFrom(after).Build();
    }

    [Fact]
    public void ASubWorkflowIsASecondWorkflowAndItsRequestPortIsUnansweredWithoutAnAnswerer()
    {
        var start = new Echo("start");
        ExecutorBinding host = Approval().BindAsExecutor("approval");
        var next = new Echo("next");
        JsonArray wfs = Workflows(new WorkflowBuilder(start).AddEdge(start, host).AddEdge(host, next).Build());

        Assert.Equal(2, wfs.Count);
        JsonObject h = NodeOf(wfs[0]!, "approval");
        Assert.Equal("subflow", (string)h["kind"]!);
        Assert.Equal((string)wfs[1]!["id"]!, (string)h["subflow_ref"]!["workflow"]!);
        Assert.Empty(h["subflow_ref"]!["in_bindings"]!.AsArray());
        Assert.Contains("ExternalRequest", h["outputs"]!.AsArray().Select(o => (string)o!["type_repr"]!));
        Assert.Equal(["Any"], h["inputs"]!.AsArray().Select(i => (string)i!["type_repr"]!));

        JsonObject port = NodeOf(wfs[1]!, "ask");
        Assert.Equal("human-input", (string)port["kind"]!);
        Assert.Equal("true", (string)port["attrs"]!["request_port"]!);
    }

    [Fact]
    public void AParentStepThatReceivesTheForwardedRequestAnswersIt()
    {
        var start = new Echo("start");
        ExecutorBinding host = Approval().BindAsExecutor("approval");
        var answerer = new Answerer();
        JsonArray wfs = Workflows(new WorkflowBuilder(start).AddEdge(start, host).AddEdge(host, answerer).AddEdge(answerer, host).Build());

        JsonArray bindings = NodeOf(wfs[0]!, "approval")["subflow_ref"]!["in_bindings"]!.AsArray();
        Assert.Equal(["answerer->ask"], bindings.Select(b => $"{b!["outer"]!["node"]}->{b["inner"]!["node"]}"));
    }

    [Fact]
    public void StateIsAChannelPerScopeAndKey()
    {
        var writer = new Writer();
        var reader = new Reader();
        JsonNode wf = Workflows(new WorkflowBuilder(writer).AddEdge(writer, reader).Build(), Facts())[0]!;

        var channels = wf["channels"]!.AsArray().ToDictionary(
            c => (string)c!["name"]!,
            c => (Writers: string.Join(",", c!["writers"]!.AsArray().Select(w => (string)w!)), Readers: string.Join(",", c["readers"]!.AsArray().Select(r => (string)r!))));
        // the shared scope is used with keys that are not constants, so it is one channel
        Assert.Equal(("writer", "reader"), channels["Shared/*"]);
        Assert.Equal(("writer", ""), channels["writer/default/count"]);
        Assert.Equal(("", "reader"), channels["reader/default/seen"]);
        Assert.Equal(3, channels.Count);
    }
}
