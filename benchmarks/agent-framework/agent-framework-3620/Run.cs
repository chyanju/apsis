using Microsoft.Agents.AI.Workflows;

namespace AgentFramework3620;

public static class Run
{
    public static async Task Main()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));

        (string Name, Order Order)[] requests = [("request-1", new Order("widget", 3)), ("request-2", new Order("gadget", 5))];
        List<(string Name, StreamingRun Run)> runs = [];
        foreach ((string name, Order order) in requests)
        {
            try
            {
                runs.Add((name, await InProcessExecution.StreamAsync(Case.Build(), order, cancellationToken: timeout.Token)));
            }
            catch (InvalidOperationException e)
            {
                Console.WriteLine($"error    {name}: {e.Message}");
            }
        }

        foreach ((string name, StreamingRun run) in runs)
        {
            await foreach (WorkflowEvent evt in run.WatchStreamAsync(timeout.Token))
            {
                switch (evt)
                {
                    case ExecutorInvokedEvent e:
                        Console.WriteLine($"invoked  {name} {e.ExecutorId}");
                        break;
                    case ExecutorFailedEvent e:
                        Console.WriteLine($"failed   {name} {e.ExecutorId}: {e.Data}");
                        break;
                    case WorkflowErrorEvent e:
                        Console.WriteLine($"error    {name}: {e.Data}");
                        break;
                    case WorkflowOutputEvent e:
                        Console.WriteLine($"output   {name} {e.Data}");
                        break;
                }
            }
        }

        foreach ((_, StreamingRun run) in runs)
        {
            await run.DisposeAsync();
        }

        Console.WriteLine("run ended");
    }
}
