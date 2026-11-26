using Xunit;

namespace Apsis.AgentFramework.Dotnet.Tests;

public class SourceFactsTests
{
    private const string Source = """
        using System;
        using System.Collections.Generic;
        using System.Threading;
        using System.Threading.Tasks;
        using Microsoft.Agents.AI.Workflows;

        namespace Probe;

        public sealed record Ping(string Text);

        public interface IMark;

        public class Note;

        public sealed class Reminder : Note, IMark;

        internal sealed class Sender() : Executor<string>("sender")
        {
            public override async ValueTask HandleAsync(string message, IWorkflowContext context, CancellationToken cancellationToken = default)
            {
                await context.SendMessageAsync(new Ping(message), cancellationToken: cancellationToken);
                await context.YieldOutputAsync(message.Length, cancellationToken);
            }

            internal sealed class Nested() : Executor<int>("nested")
            {
                public override ValueTask HandleAsync(int message, IWorkflowContext context, CancellationToken cancellationToken = default)
                    => context.SendMessageAsync(new List<Ping>(), cancellationToken: cancellationToken);
            }
        }

        internal sealed class Counter() : Executor<string>("counter")
        {
            public override async ValueTask HandleAsync(string message, IWorkflowContext context, CancellationToken cancellationToken = default)
                => await context.QueueStateUpdateAsync("log", (await context.ReadStateAsync<string>("log")) + message);
        }

        internal sealed class Notifier() : Executor<string>("notifier")
        {
            public override ValueTask HandleAsync(string message, IWorkflowContext context, CancellationToken cancellationToken = default)
                => context.SendMessageAsync(new Reminder(), cancellationToken: cancellationToken);
        }

        internal sealed class Quiet() : Executor<string, string>("quiet")
        {
            public override ValueTask<string> HandleAsync(string message, IWorkflowContext context, CancellationToken cancellationToken = default)
                => ValueTask.FromResult(message);
        }
        """;

    [Fact]
    public void SendsAndYieldsAreReadPerDeclaringClass()
    {
        IEnumerable<string> dependencies = Directory.EnumerateFiles(AppContext.BaseDirectory, "Microsoft.*.dll");
        SourceFacts facts = SourceFacts.FromSources([("Probe.cs", Source)], dependencies);

        Assert.Equal(0, facts.UnresolvedCalls);
        Assert.Equal(["Ping"], facts.Sends["Probe.Sender"]);
        Assert.Equal(["int"], facts.Yields["Probe.Sender"]);
        Assert.Equal(["list[Ping]"], facts.Sends["Probe.Sender+Nested"]);
        Assert.False(facts.Sends.ContainsKey("Probe.Quiet"));
        Assert.Equal([new StateAccess(true, false, null, "log"), new StateAccess(false, true, null, "log")], facts.State["Probe.Counter"]);
        Assert.Equal(["IMark", "Note"], facts.Supertypes["Reminder"]);
        Assert.False(facts.Supertypes.ContainsKey("Ping"));
    }
}
