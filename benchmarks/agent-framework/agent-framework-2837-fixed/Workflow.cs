using Microsoft.Agents.AI.Workflows;

namespace AgentFramework2837;

public class BaseClass
{
    public virtual string GetName() => "BaseClass";
}

public class DerivedClass : BaseClass
{
    public override string GetName() => "DerivedClass";
}

internal sealed class DispatchExecutor() : Executor<string, DerivedClass>("DispatchExecutor")
{
    public override ValueTask<DerivedClass> HandleAsync(string message, IWorkflowContext context, CancellationToken cancellationToken = default)
        => ValueTask.FromResult(new DerivedClass());
}

internal sealed class IntrospectionExecutor() : Executor<DerivedClass, string>("IntrospectionExecutor")
{
    public override ValueTask<string> HandleAsync(DerivedClass message, IWorkflowContext context, CancellationToken cancellationToken = default)
        => ValueTask.FromResult(message.GetType().Name);
}

public static class Case
{
    public static Workflow Build()
    {
        var dispatch = new DispatchExecutor();
        var introspect = new IntrospectionExecutor();
        return new WorkflowBuilder(dispatch)
            .AddEdge(dispatch, introspect)
            .WithOutputFrom(introspect)
            .Build();
    }
}
