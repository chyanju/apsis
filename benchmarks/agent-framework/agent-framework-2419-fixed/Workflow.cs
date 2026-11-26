using Microsoft.Agents.AI.Workflows;

namespace AgentFramework2419;

public static class Case
{
    public static Workflow Build()
    {
        TextReadExecutor textRead = new();
        TextTrimExecutor textTrim = new();
        CharCountingExecutor charCount = new();

        return new WorkflowBuilder(textRead)
            .AddEdge(textRead, textTrim)
            .AddEdge(textTrim, charCount)
            .WithOutputFrom(charCount)
            .Build();
    }
}

internal static class Constants
{
    public const string WordStateScope = "WordStateScope";
}

internal sealed class TextReadExecutor() : Executor<string, string>("TextReadExecutor")
{
    public override async ValueTask<string> HandleAsync(string word, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        string key = Guid.NewGuid().ToString();
        await context.QueueStateUpdateAsync(key, word, scopeName: Constants.WordStateScope, cancellationToken);

        return key;
    }
}

internal sealed class TextTrimExecutor() : Executor<string, string>("TextTrimExecutor")
{
    public override async ValueTask<string> HandleAsync(string key, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        var content = await context.ReadStateAsync<string>(key, scopeName: Constants.WordStateScope, cancellationToken)
            ?? throw new InvalidOperationException("Word state not found");

        var trimmed = content.Trim();

        await context.QueueStateUpdateAsync(key, trimmed, scopeName: Constants.WordStateScope, cancellationToken);

        return key;
    }
}

internal sealed class CharCountingExecutor() : Executor<string, int>("CharCountingExecutor")
{
    public override async ValueTask<int> HandleAsync(string message, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        var content = await context.ReadStateAsync<string>(message, scopeName: Constants.WordStateScope, cancellationToken);

        int charCount = content?.Length ?? 0;

        return charCount;
    }
}
