using System.Runtime.CompilerServices;
using System.Text.Json.Nodes;
using Microsoft.Agents.AI;
using Microsoft.Agents.AI.Workflows;
using Microsoft.Extensions.AI;
using Xunit;

namespace Apsis.AgentFramework.Dotnet.Tests;

public class Base;

public sealed class Derived : Base;

internal sealed class Dispatch() : Executor<string, Derived>("dispatch")
{
    public override ValueTask<Derived> HandleAsync(string message, IWorkflowContext context, CancellationToken cancellationToken = default)
        => ValueTask.FromResult(new Derived());
}

internal sealed class Introspect() : Executor<Base, string>("introspect")
{
    public override ValueTask<string> HandleAsync(Base message, IWorkflowContext context, CancellationToken cancellationToken = default)
        => ValueTask.FromResult(message.GetType().Name);
}

internal sealed class Echo(string id) : Executor<string, string>(id)
{
    public override ValueTask<string> HandleAsync(string message, IWorkflowContext context, CancellationToken cancellationToken = default)
        => ValueTask.FromResult(message);
}

internal sealed class SilentChatClient : IChatClient
{
    public Task<ChatResponse> GetResponseAsync(IEnumerable<ChatMessage> messages, ChatOptions? options = null, CancellationToken cancellationToken = default)
        => Task.FromResult(new ChatResponse(new ChatMessage(ChatRole.Assistant, "ok")));

    public async IAsyncEnumerable<ChatResponseUpdate> GetStreamingResponseAsync(
        IEnumerable<ChatMessage> messages,
        ChatOptions? options = null,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        await Task.Yield();
        yield return new ChatResponseUpdate(ChatRole.Assistant, "ok");
    }

    public object? GetService(Type serviceType, object? serviceKey = null) => null;

    public void Dispose()
    {
    }
}

public class ExtractorTests
{
    private static JsonObject Extract(Workflow workflow) =>
        (JsonObject)Extractor.Program(workflow, new SourceFacts(), "test")["workflows"]![0]!;

    private static JsonObject NodeOf(JsonObject wf, string id) =>
        (JsonObject)wf["nodes"]!.AsArray().Single(n => (string)n!["id"]! == id)!;

    private static string[] TypesOf(JsonObject node, string sockets) =>
        node[sockets]!.AsArray().Select(s => (string)s!["type_repr"]!).ToArray();

    private static string[] EdgesOf(JsonObject wf) =>
        wf["edges"]!.AsArray().Select(e => $"{e!["from"]!["node"]}->{e["to"]!["node"]}:{e["kind"]}").ToArray();

    [Fact]
    public void ExecutorsHandlersAndEdgesAreRead()
    {
        var dispatch = new Dispatch();
        var introspect = new Introspect();
        Workflow workflow = new WorkflowBuilder(dispatch).AddEdge(dispatch, introspect).WithOutputFrom(introspect).Build();

        JsonObject wf = Extract(workflow);
        Assert.Equal("group-chat-speaker", (string)wf["execution_model"]!);
        Assert.Equal(["dispatch"], wf["start_nodes"]!.AsArray().Select(n => (string)n!));
        Assert.Equal(["introspect"], wf["output_nodes"]!.AsArray().Select(n => (string)n!));
        Assert.Equal(["dispatch->introspect:control"], EdgesOf(wf));

        JsonObject d = NodeOf(wf, "dispatch");
        Assert.Equal(["string"], TypesOf(d, "inputs"));
        Assert.Equal(["Derived"], TypesOf(d, "outputs"));
        Assert.Equal("", (string)d["attrs"]!["workflow_output_types"]!);

        JsonObject i = NodeOf(wf, "introspect");
        Assert.Equal(["Base"], TypesOf(i, "inputs"));
        Assert.Equal("string", (string)i["attrs"]!["workflow_output_types"]!);
        Assert.Null(i["attrs"]!["fan_in_delivery"]);
    }

    [Fact]
    public void AFanInTargetReceivesEachMessageOnItsOwn()
    {
        var start = new Echo("start");
        var a = new Echo("a");
        var b = new Echo("b");
        var agg = new Echo("agg");
        Workflow workflow = new WorkflowBuilder(start).AddFanOutEdge(start, [a, b]).AddFanInEdge([a, b], agg).WithOutputFrom(agg).Build();

        JsonObject wf = Extract(workflow);
        Assert.Equal(["a->agg:control", "b->agg:control", "start->a:control", "start->b:control"], EdgesOf(wf));
        Assert.Equal("each", (string)NodeOf(wf, "agg")["attrs"]!["fan_in_delivery"]!);
        Assert.Null(NodeOf(wf, "a")["attrs"]!["fan_in_delivery"]);
    }

    [Fact]
    public void AConditionalEdgeIsMarked()
    {
        var start = new Echo("start");
        var next = new Echo("next");
        Workflow workflow = new WorkflowBuilder(start).AddEdge<string>(start, next, condition: s => s == "go").Build();

        Assert.Equal(["start->next:conditional"], EdgesOf(Extract(workflow)));
    }

    [Fact]
    public void AnAgentNodeIsNamedAfterTheAgentAndSendsItsResponse()
    {
        var start = new Echo("start");
        AIAgent agent = new ChatClientAgent(new SilentChatClient(), name: "Responder");
        Workflow workflow = new WorkflowBuilder(start).AddEdge(start, agent).Build();

        JsonObject wf = Extract(workflow);
        JsonObject node = NodeOf(wf, "Responder");
        Assert.Equal("agent", (string)node["kind"]!);
        Assert.Equal("Responder", (string)node["name"]!);
        Assert.Equal(["TurnToken", "list[ChatMessage]"], TypesOf(node, "outputs"));
        Assert.Contains("ChatMessage", TypesOf(node, "inputs"));
        Assert.Equal(["start->Responder:control"], EdgesOf(wf));
    }
}
