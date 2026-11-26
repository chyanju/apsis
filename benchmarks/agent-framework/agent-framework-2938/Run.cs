using Microsoft.Agents.AI.Workflows;
using Microsoft.Extensions.AI;

namespace AgentsInWorkflows;

public static class Run
{
    public static async Task Main()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(60));
        await using StreamingRun run = await InProcessExecution.StreamAsync(Case.Build(), new ChatMessage(ChatRole.User, "Translate this message: Hello World!"), cancellationToken: timeout.Token);
        await run.TrySendMessageAsync(new TurnToken(emitEvents: true));
        await foreach (WorkflowEvent evt in run.WatchStreamAsync(timeout.Token))
        {
            switch (evt)
            {
                case ExecutorInvokedEvent e:
                    Console.WriteLine($"invoked  {e.ExecutorId}");
                    break;
                case ExecutorFailedEvent e:
                    Console.WriteLine($"failed   {e.ExecutorId}: {e.Data}");
                    break;
                case WorkflowErrorEvent e:
                    Console.WriteLine($"error    {e.Data}");
                    break;
                case WorkflowOutputEvent e:
                    Console.WriteLine($"output   {Describe(e.Data)}");
                    break;
            }
        }

        Console.WriteLine("run ended");
    }

    private static string? Describe(object? data) => data is IEnumerable<ChatMessage> messages
        ? string.Join(" | ", messages.Select(m => $"{m.Role}: {m.Text}"))
        : data?.ToString();
}
