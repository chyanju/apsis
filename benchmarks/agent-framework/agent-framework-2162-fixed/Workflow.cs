using Microsoft.Agents.AI.Workflows;

namespace AgentFramework2162;

public static class Case
{
    public static Workflow Build()
    {
        StoreTextExecutor storeText = new();
        WordCountExecutor wordCount = new();

        return new WorkflowBuilder(storeText)
            .AddEdge(storeText, wordCount)
            .WithOutputFrom(wordCount)
            .Build();
    }
}

internal static class Constants
{

    public const string FlowStateScope = "FlowStateScope";
}

internal sealed class StoreTextExecutor() : Executor<string, string>("StoreTextExecutor")
{
    public override async ValueTask<string> HandleAsync(string text, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        string key = Guid.NewGuid().ToString("N");
        await context.QueueStateUpdateAsync(key, text, scopeName: Constants.FlowStateScope, cancellationToken);

        return key;
    }
}

internal sealed class WordCountExecutor() : Executor<string, int>("WordCountExecutor")
{
    public override async ValueTask<int> HandleAsync(string key, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        string text = await context.ReadStateAsync<string>(key, scopeName: Constants.FlowStateScope, cancellationToken)
            ?? throw new InvalidOperationException("Text not found in state");

        return text.Split(' ', StringSplitOptions.RemoveEmptyEntries).Length;
    }
}
