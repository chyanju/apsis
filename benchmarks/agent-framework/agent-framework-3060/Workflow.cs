using System.Runtime.CompilerServices;
using Microsoft.Agents.AI.Workflows;
using Microsoft.Extensions.AI;

namespace AgentFramework3060;

public sealed record RoundData(string Topic, int Round);

public sealed record Stance(string Side, string Text, int Round);

internal sealed class StartNode() : Executor<string, RoundData>("StartNode")
{
    public override ValueTask<RoundData> HandleAsync(string message, IWorkflowContext context, CancellationToken cancellationToken = default)
        => ValueTask.FromResult(new RoundData(message, 1));
}

internal sealed class RoundGate() : Executor<RoundData, RoundData>("Round_Gate")
{
    public override ValueTask<RoundData> HandleAsync(RoundData message, IWorkflowContext context, CancellationToken cancellationToken = default)
        => ValueTask.FromResult(message);
}

internal sealed class DebaterExecutor(string id, string side, IChatClient model) : Executor<RoundData, Stance>(id)
{
    public override async ValueTask<Stance> HandleAsync(RoundData message, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        ChatResponse response = await model.GetResponseAsync(
            [new ChatMessage(ChatRole.User, $"Round {message.Round}. Argue the {side} case on: {message.Topic}")],
            new ChatOptions { Instructions = $"You are the {side} side of a debate." },
            cancellationToken);
        return new Stance(side, response.Text, message.Round);
    }
}

internal sealed class MergeRoundExecutor() : StatefulExecutor<List<Stance>, Stance>("Merge_Round", () => [])
{
    public override ValueTask HandleAsync(Stance message, IWorkflowContext context, CancellationToken cancellationToken = default)
        => this.InvokeWithStateAsync(async (state, ctx, ct) =>
        {
            state.Add(message);
            if (state.Count < 2)
            {
                Console.WriteLine($"[{this.Id}] round {message.Round}: not completed");
                return state;
            }

            Console.WriteLine($"[{this.Id}] round {message.Round}: completed");
            await ctx.SendMessageAsync(new RoundData(string.Join(" | ", state.Select(s => s.Text)), message.Round), cancellationToken: ct);
            return [];
        }, context, cancellationToken: cancellationToken);
}

internal sealed class FuncAgentActionExecutor() : Executor<RoundData, RoundData>("FuncAgentAction")
{
    public override ValueTask<RoundData> HandleAsync(RoundData message, IWorkflowContext context, CancellationToken cancellationToken = default)
        => ValueTask.FromResult(message with { Round = message.Round + 1 });
}

internal sealed class FinalJudgmentExecutor() : Executor<RoundData, string>("Final_Judgment")
{
    public override ValueTask<string> HandleAsync(RoundData message, IWorkflowContext context, CancellationToken cancellationToken = default)
        => ValueTask.FromResult($"verdict after {message.Round - 1} rounds: {message.Topic}");
}

public static class Case
{

    public const int Rounds = 100;

    public static Workflow Build()
    {
        IChatClient model = new CannedChatClient();

        StartNode startNode = new();
        RoundGate roundGate = new();
        DebaterExecutor bullRound = new("Bull_Round", "bull", model);
        DebaterExecutor bearRound = new("Bear_Round", "bear", model);
        MergeRoundExecutor mergeRound = new();
        FuncAgentActionExecutor funcAgentAction = new();
        FinalJudgmentExecutor finalJudgment = new();

        return new WorkflowBuilder(startNode)
            .AddEdge(startNode, roundGate)
            .AddFanOutEdge(roundGate, [bullRound, bearRound])

            .AddFanInEdge([bullRound, bearRound], mergeRound)
            .AddEdge(mergeRound, funcAgentAction)
            .AddEdge<RoundData>(funcAgentAction, roundGate, condition: next => next!.Round <= Rounds)
            .AddEdge<RoundData>(funcAgentAction, finalJudgment, condition: next => next!.Round > Rounds)
            .WithOutputFrom(finalJudgment)
            .Build();
    }
}

internal sealed class CannedChatClient : IChatClient
{
    private static readonly TimeSpan Latency = TimeSpan.FromMilliseconds(20);

    public async Task<ChatResponse> GetResponseAsync(IEnumerable<ChatMessage> messages, ChatOptions? options = null, CancellationToken cancellationToken = default)
    {
        await Task.Delay(Latency, cancellationToken);
        return new ChatResponse(new ChatMessage(ChatRole.Assistant, Reply(messages, options)));
    }

    public async IAsyncEnumerable<ChatResponseUpdate> GetStreamingResponseAsync(
        IEnumerable<ChatMessage> messages,
        ChatOptions? options = null,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        await Task.Delay(Latency, cancellationToken);
        yield return new ChatResponseUpdate(ChatRole.Assistant, Reply(messages, options));
    }

    public object? GetService(Type serviceType, object? serviceKey = null) => null;

    public void Dispose()
    {
    }

    private static string Reply(IEnumerable<ChatMessage> messages, ChatOptions? options)
    {
        string round = messages.LastOrDefault(m => m.Role == ChatRole.User)?.Text.Split('.')[0] ?? "Round ?";
        return options?.Instructions?.Contains("bull", StringComparison.Ordinal) is true
            ? $"{round}, bull: rate cuts will lift earnings."
            : $"{round}, bear: valuations already price the cuts in.";
    }
}
