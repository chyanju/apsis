using Microsoft.Agents.AI.Workflows;

namespace AgentFramework4520;

public static class Run
{
    public static async Task Main()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        await using StreamingRun run = await InProcessExecution.RunStreamingAsync(Case.Build(), "start", cancellationToken: timeout.Token);
        await foreach (WorkflowEvent evt in run.WatchStreamAsync(timeout.Token))
        {
            switch (evt)
            {
                case ExecutorInvokedEvent e:
                    Console.WriteLine($"invoked  {e.ExecutorId}: {e.Data}");
                    break;
                case ExecutorFailedEvent e:
                    Console.WriteLine($"failed   {e.ExecutorId}: {Describe(e.Data)}");
                    break;
                case WorkflowErrorEvent e:
                    Console.WriteLine($"error    {Describe(e.Exception)}");
                    break;
                case WorkflowOutputEvent e:
                    Console.WriteLine($"output   {e.ExecutorId}: {e.Data}");
                    break;
            }
        }

        Console.WriteLine("run ended");
    }

    private static string Describe(Exception? e)
    {
        if (e is null)
        {
            return "(no exception)";
        }

        string text = $"{e.GetType().FullName}: {e.Message}";
        return e.InnerException is null ? text : $"{text} ---> {Describe(e.InnerException)}";
    }
}
