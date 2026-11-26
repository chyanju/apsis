using Microsoft.Agents.AI.Workflows;

namespace AgentFramework2837;

public static class Run
{
    public static async Task Main()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        await using StreamingRun run = await InProcessExecution.StreamAsync(Case.Build(), "go", cancellationToken: timeout.Token);
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
                    Console.WriteLine($"output   {e.Data}");
                    break;
            }
        }

        Console.WriteLine("run ended");
    }
}
