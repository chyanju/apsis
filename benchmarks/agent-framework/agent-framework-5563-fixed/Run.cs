using Microsoft.Agents.AI.Workflows;

namespace AgentFramework5563;

public static class Run
{
    public static async Task Main()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using StreamingRun run = await InProcessExecution.RunStreamingAsync(Case.Build(), NumberSignal.Init, cancellationToken: timeout.Token);

        int min = 0, max = 100, guess = 0;
        try
        {
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
                    case RequestInfoEvent e when e.Request.TryGetDataAs(out NumberSignal signal):
                        if (signal == NumberSignal.Above)
                        {
                            max = guess - 1;
                        }
                        else if (signal == NumberSignal.Below)
                        {
                            min = guess + 1;
                        }

                        guess = (min + max) / 2;
                        Console.WriteLine($"request  {e.Request.PortInfo.PortId} ({signal}): answered {guess}");
                        await run.SendResponseAsync(e.Request.CreateResponse(guess));
                        break;
                    case RequestInfoEvent e:
                        Console.WriteLine($"request  {e.Request.PortInfo.PortId}: {e.Request.Data}");
                        break;
                }
            }
        }
        catch (OperationCanceledException)
        {
        }

        if (timeout.IsCancellationRequested)
        {
            Console.WriteLine($"timed out, run status {await run.GetStatusAsync()}");
        }

        Console.WriteLine("run ended");
    }

    private static string Describe(object? data) =>
        data is Exception ex ? $"{ex.GetBaseException().GetType().Name}: {ex.GetBaseException().Message}" : $"{data}";
}
