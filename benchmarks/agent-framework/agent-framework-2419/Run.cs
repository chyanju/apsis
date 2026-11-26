using Microsoft.Agents.AI.Workflows;

namespace AgentFramework2419;

public static class Run
{
    public static async Task Main()
    {
        var text = "    Lorem ipsum dolor sit amet, consectetur adipiscing elit.  ";

        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        await using StreamingRun run = await InProcessExecution.StreamAsync(Case.Build(), text, cancellationToken: timeout.Token);
        await foreach (WorkflowEvent evt in run.WatchStreamAsync(timeout.Token))
        {
            switch (evt)
            {
                case ExecutorInvokedEvent e:
                    Console.WriteLine($"invoked  {e.ExecutorId}");
                    break;
                case ExecutorFailedEvent e:
                    Console.WriteLine($"failed   {e.ExecutorId}: {Describe(e.Data)}");
                    break;
                case WorkflowErrorEvent e:
                    Console.WriteLine($"error    {Describe(e.Data)}");
                    break;
                case WorkflowOutputEvent e:
                    Console.WriteLine($"output   {e.Data}");
                    break;
            }
        }

        Console.WriteLine("run ended");
    }

    private static string Describe(object? data) =>
        data is Exception ex ? $"{ex.GetBaseException().GetType().Name}: {ex.GetBaseException().Message}" : $"{data}";
}
