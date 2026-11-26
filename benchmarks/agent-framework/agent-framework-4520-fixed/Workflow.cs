using Microsoft.Agents.AI.Workflows;

namespace AgentFramework4520;

public static class Case
{
    public static Workflow Build()
    {
        var executor1 = new StartExecutor("step 1", "1");
        var executor2 = new TestExecutor("step 2", "2");
        var executor3 = new TestExecutor("step 3", "3");
        var executor4 = new TestExecutor("step 4", "4");
        var executor5 = new TestExecutor("step 5", "5");
        var executor6 = new EndExecutor("step 6", "6");
        return new WorkflowBuilder(executor1).AddEdge(executor1, executor2)
            .AddFanOutEdge(executor2, [executor3, executor4, executor5])
            .AddFanInBarrierEdge([executor3, executor4, executor5], executor6)
            .WithOutputFrom(executor6)
            .Build();
    }
}

internal sealed partial class TestExecutor : Executor<string, string>
{
    private readonly string _message;
    private readonly string _name;

    public TestExecutor(string message, string name) : base(name)
    {
        _message = message;
        _name = name;
    }

    public override ValueTask<string> HandleAsync(string message, IWorkflowContext context, CancellationToken cancellationToken = default)
        => ValueTask.FromResult(_message + " " + _name);
}

internal sealed partial class StartExecutor : Executor<string, string>
{
    private readonly string _message;
    private readonly string _name;

    public StartExecutor(string message, string name) : base(name)
    {
        _message = message;
        _name = name;
    }

    public override ValueTask<string> HandleAsync(string message, IWorkflowContext context, CancellationToken cancellationToken = default)
        => ValueTask.FromResult(_message + " " + _name + " " + message);
}

[YieldsOutput(typeof(string))]
internal sealed partial class EndExecutor : Executor<string>
{
    private string _message;
    private int count;
    private readonly string _name;

    public EndExecutor(string message, string name) : base(name)
    {
        _message = message;
        _name = name;
    }

    public override async ValueTask HandleAsync(string message, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        this._message += " " + message;
        count++;
        if (count == 3)
        {
            await context.YieldOutputAsync(_message);
        }
    }
}
