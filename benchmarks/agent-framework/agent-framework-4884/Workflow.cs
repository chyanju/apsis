using Microsoft.Agents.AI.Workflows;

namespace AgentFramework4884;

public static class Case
{
    public static Workflow Build()
    {
        var start = new StartExec();
        var a = new AExec();
        var b = new BExec();
        var agg = new AggExec();

        return new WorkflowBuilder(start)
            .AddFanOutEdge(start, [a, b])
            .AddFanInBarrierEdge([a, b], agg)
            .WithOutputFrom(agg)
            .Build();
    }
}

internal sealed class StartExec() : Executor<string, string>("start")
{
    public override ValueTask<string> HandleAsync(
        string input,
        IWorkflowContext context,
        CancellationToken cancellationToken = default)
    {
        Console.WriteLine("start");
        return ValueTask.FromResult($"{input}-start");
    }
}

internal sealed class AExec() : Executor<string, string>("a")
{
    public override ValueTask<string> HandleAsync(
        string input,
        IWorkflowContext context,
        CancellationToken cancellationToken = default)
    {
        Console.WriteLine("a");
        return ValueTask.FromResult($"{input}-a");
    }
}

internal sealed class BExec() : Executor<string, string>("b")
{
    public override ValueTask<string> HandleAsync(
        string input,
        IWorkflowContext context,
        CancellationToken cancellationToken = default)
    {
        Console.WriteLine("b");
        return ValueTask.FromResult($"{input}-b");
    }
}

internal sealed class AggExec() : Executor<List<string>, string>("agg")
{
    public override ValueTask<string> HandleAsync(
        List<string> input,
        IWorkflowContext context,
        CancellationToken cancellationToken = default)
    {
        Console.WriteLine($"agg:{input.Count}");
        return ValueTask.FromResult(string.Join(",", input));
    }
}
