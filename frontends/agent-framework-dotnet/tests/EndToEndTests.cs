using System.Runtime.CompilerServices;
using System.Text.Json.Nodes;
using Xunit;

namespace Apsis.AgentFramework.Dotnet.Tests;

/// Build, load and extract C# artifacts of `benchmarks/agent-framework/`, one per SDK shape the front-end reads.
public class EndToEndTests
{
    private static string Benchmark([CallerFilePath] string here = "") =>
        Path.GetFullPath(Path.Combine(Path.GetDirectoryName(here)!, "..", "..", "..", "benchmarks", "agent-framework"));

    private static JsonArray Run(string artifact)
    {
        string dir = Path.Combine(Benchmark(), artifact);
        string entry = (string)JsonNode.Parse(File.ReadAllText(Path.Combine(dir, "meta.json")))!["entry"]!;
        string output = Path.Combine(Path.GetTempPath(), $"apsis-ir-{Guid.NewGuid():N}.json");
        try
        {
            Assert.Equal(0, Program.Main([Path.Combine(dir, entry), "-o", output]));
            return JsonNode.Parse(File.ReadAllText(output))!["workflows"]!.AsArray();
        }
        finally
        {
            File.Delete(output);
        }
    }

    private static JsonObject Node(JsonNode wf, string id) =>
        (JsonObject)wf["nodes"]!.AsArray().Single(n => (string)n!["id"]! == id)!;

    private static string[] Types(JsonNode wf, string id, string sockets) =>
        Node(wf, id)[sockets]!.AsArray().Select(s => (string)s!["type_repr"]!).ToArray();

    private static string? Attr(JsonNode wf, string id, string key) => (string?)Node(wf, id)["attrs"]![key];

    private static string[] Edges(JsonNode wf) =>
        wf["edges"]!.AsArray().Select(e => $"{e!["from"]!["node"]}->{e["to"]!["node"]}").ToArray();

    [Fact]
    public void ExecutorRegistrationsAndAFanInOfRelease1_0_0Preview251028()
    {
        JsonNode wf = Run("agent-framework-1814")[0]!;
        Assert.Equal("1.0.0-preview.251028.1", (string)wf["framework_version"]!);
        Assert.Equal("agent", (string)Node(wf, "Physicist")["kind"]!);
        Assert.Equal("agent", (string)Node(wf, "Chemist")["kind"]!);
        Assert.Equal("true", Attr(wf, "ConcurrentAggregationExecutor", "barrier_join"));
        Assert.Equal("each", Attr(wf, "ConcurrentAggregationExecutor", "fan_in_delivery"));
    }

    [Fact]
    public void AgentsAndTheMessagesAHandlerSends()
    {
        JsonNode wf = Run("agent-framework-2181")[0]!;
        Assert.Equal("1.0.0-preview.251112.1", (string)wf["framework_version"]!);
        Assert.Equal(["ChatMessage", "TurnToken"], Types(wf, "StringToChat", "outputs"));
        Assert.Equal(["ChatMessage"], Types(wf, "JailbreakSync", "inputs"));
        Assert.Contains("JailbreakDetector->JailbreakSync", Edges(wf));
    }

    [Fact]
    public void StateAcrossASubWorkflow()
    {
        JsonArray wfs = Run("agent-framework-2419");
        Assert.Equal(2, wfs.Count);
        Assert.Equal("subflow", (string)Node(wfs[0]!, "textTrim")["kind"]!);
        JsonNode channel = wfs[1]!["channels"]!.AsArray().Single()!;
        Assert.Equal("WordStateScope/*", (string)channel["name"]!);
        Assert.Equal(["TextTrimExecutor"], channel["writers"]!.AsArray().Select(w => (string)w!));
        Assert.Equal("WordStateScope/*", Attr(wfs[1]!, "TextTrimExecutor", "reads_before_write"));
    }

    [Fact]
    public void AHandlerTypedForTheExactMessage()
    {
        JsonNode wf = Run("agent-framework-2837-fixed")[0]!;
        Assert.Equal("1.0.0-preview.251204.1", (string)wf["framework_version"]!);
        Assert.Equal(["DerivedClass"], Types(wf, "DispatchExecutor", "outputs"));
        Assert.Equal(["DerivedClass"], Types(wf, "IntrospectionExecutor", "inputs"));
    }

    [Fact]
    public void AWorkflowRunByAnAgentInAHandoff()
    {
        JsonArray wfs = Run("agent-framework-3766");
        JsonObject host = Node(wfs[0]!, "HitlWorkflow_hitl_workflow");
        Assert.Equal("agent", (string)host["kind"]!);
        Assert.Empty(host["subflow_ref"]!["in_bindings"]!.AsArray());
        JsonNode inner = wfs.Single(w => (string)w!["id"]! == (string)host["subflow_ref"]!["workflow"]!)!;
        Assert.Equal("true", Attr(inner, "GuessNumber", "request_port"));
        Assert.Equal(["int"], Types(inner, "GuessNumber", "outputs"));
    }

    [Fact]
    public void TheAgentAndOutputExecutorsOfASequentialAgentWorkflow()
    {
        JsonNode wf = Run("agent-framework-2938-fixed")[0]!;
        Assert.Equal("list[ChatMessage]", Attr(wf, "OutputMessages", "workflow_output_types"));
        Assert.Null(Attr(wf, "OutputMessages", "yields_unknown"));
        JsonNode agent = wf["nodes"]!.AsArray().First(n => ((string)n!["type_name"]!).EndsWith("AgentRunStreamingExecutor", StringComparison.Ordinal))!;
        Assert.Equal(["TurnToken", "list[ChatMessage]"], agent["outputs"]!.AsArray().Select(s => (string)s!["type_repr"]!));
    }

    [Fact]
    public void DeclaredOutputTypesOfReleaseCandidate3()
    {
        Assert.Equal("", Attr(Run("agent-framework-4520")[0]!, "6", "workflow_output_types"));
        Assert.Equal("string", Attr(Run("agent-framework-4520-fixed")[0]!, "6", "workflow_output_types"));
    }

    [Fact]
    public void DeclaredSendsOfRelease1_1()
    {
        JsonNode wf = Run("agent-framework-5380")[0]!;
        Assert.Equal("", Attr(wf, "IntentRoutingExecutor", "declared_sends"));
        Assert.Equal(["list[IntentResult]"], Types(wf, "IntentRoutingExecutor", "outputs"));
    }

    [Fact]
    public void AWorkflowObjectHandedToEveryCaller()
    {
        Assert.Equal("true", (string?)Run("agent-framework-3620")[0]!["attrs"]?["shared_workflow"]);
        Assert.Null(Run("agent-framework-3620-fixed")[0]!["attrs"]);
    }

    [Fact]
    public void AParentPortAnswersTheRequestsOfASubWorkflow()
    {
        JsonNode wf = Run("agent-framework-5563-fixed")[0]!;
        JsonArray bindings = Node(wf, "Subworkflow")["subflow_ref"]!["in_bindings"]!.AsArray();
        Assert.Equal(["ExternalGuessNumber->GuessNumber"], bindings.Select(b => $"{b!["outer"]!["node"]}->{b["inner"]!["node"]}"));
    }
}
