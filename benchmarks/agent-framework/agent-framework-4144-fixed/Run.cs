using Microsoft.Agents.AI.Workflows;

namespace WorkflowHumanInTheLoopBasicSample;

public static class Run
{
    public static async Task Main()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));

        Queue<int> guesses = new([50, 25, 42]);

        await using StreamingRun run = await InProcessExecution.RunStreamingAsync(Case.Build(), NumberSignal.Init, cancellationToken: timeout.Token);
        await foreach (WorkflowEvent evt in run.WatchStreamAsync(timeout.Token))
        {
            switch (evt)
            {
                case RequestInfoEvent e:
                    e.Request.TryGetDataAs(out NumberSignal signal);
                    int guess = guesses.Dequeue();
                    Console.WriteLine($"request  {e.Request.PortInfo.PortId} {signal}: answered {guess}");
                    await run.SendResponseAsync(e.Request.CreateResponse(guess));
                    break;
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
        data is Exception e ? $"{e.GetBaseException().GetType().Name}: {e.GetBaseException().Message}" : $"{data}";
}
