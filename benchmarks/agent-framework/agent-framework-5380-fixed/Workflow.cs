using System.Runtime.CompilerServices;
using Microsoft.Agents.AI;
using Microsoft.Agents.AI.Workflows;
using Microsoft.Extensions.AI;

namespace AgentFramework5380;

public static class Case
{
    public static Workflow Build()
    {
        AIAgent intentAgent = new ChatClientAgent(
            new CannedChatClient(),
            name: "IntentAgent",
            instructions: "Classify the user's message into the intents it expresses, each with a confidence between 0 and 1.");

        var routing = new IntentRoutingExecutor(intentAgent);
        var dispatch = new IntentDispatchExecutor();
        return new WorkflowBuilder(routing)
            .AddEdge(routing, dispatch)
            .Build();
    }
}

public sealed record ChatInput(string SessionId, string Message);

public sealed record IntentResult(string Name, double Confidence);

[SendsMessage(typeof(List<IntentResult>))]
public class IntentRoutingExecutor(AIAgent agent) : Executor<ChatInput>(nameof(IntentRoutingExecutor))
{
    public override async ValueTask HandleAsync(ChatInput message, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        var messages = new List<ChatMessage>();
        messages.Add(new ChatMessage(ChatRole.User, message.Message));

        var result = await agent.RunAsync<List<IntentResult>>(messages, cancellationToken: cancellationToken);

        await context.SendMessageAsync(result.Result, cancellationToken: cancellationToken);
    }
}

public sealed class IntentDispatchExecutor() : Executor<List<IntentResult>>(nameof(IntentDispatchExecutor))
{
    public override ValueTask HandleAsync(List<IntentResult> message, IWorkflowContext context, CancellationToken cancellationToken = default)
        => default;
}

internal sealed class CannedChatClient : IChatClient
{
    public Task<ChatResponse> GetResponseAsync(IEnumerable<ChatMessage> messages, ChatOptions? options = null, CancellationToken cancellationToken = default)
        => Task.FromResult(new ChatResponse(new ChatMessage(ChatRole.Assistant, Reply(messages))));

    public async IAsyncEnumerable<ChatResponseUpdate> GetStreamingResponseAsync(
        IEnumerable<ChatMessage> messages,
        ChatOptions? options = null,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        await Task.Yield();
        yield return new ChatResponseUpdate(ChatRole.Assistant, Reply(messages));
    }

    public object? GetService(Type serviceType, object? serviceKey = null) => null;

    public void Dispose()
    {
    }

    private static string Reply(IEnumerable<ChatMessage> messages)
    {
        string last = messages.LastOrDefault(m => m.Role == ChatRole.User)?.Text ?? string.Empty;
        var intents = new List<string>();
        if (last.Contains("weather", StringComparison.OrdinalIgnoreCase))
        {
            intents.Add("""{"name":"check_weather","confidence":0.91}""");
        }

        if (last.Contains("remind", StringComparison.OrdinalIgnoreCase))
        {
            intents.Add("""{"name":"set_reminder","confidence":0.62}""");
        }

        return $$"""{"data":[{{string.Join(",", intents)}}]}""";
    }
}
