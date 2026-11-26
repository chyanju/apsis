using Microsoft.Agents.AI.Workflows;

namespace WorkflowCustomAgentExecutorsSample;

public static class Run
{
    public static async Task Main()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(60));
        await using StreamingRun run = await InProcessExecution.RunStreamingAsync(Case.Build(), "Create a slogan for a new electric SUV that is affordable and fun to drive.", cancellationToken: timeout.Token);
        await foreach (WorkflowEvent evt in run.WatchStreamAsync(timeout.Token))
        {
            switch (evt)
            {
                case SloganGeneratedEvent e:
                    Console.WriteLine($"event    {e}");
                    break;
                case FeedbackEvent { Data: FeedbackResult feedback }:
                    Console.WriteLine($"event    Feedback: rating {feedback.Rating}, {feedback.Comments}");
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
                    Console.WriteLine($"output   {e.Data?.ToString()?.ReplaceLineEndings(" ")}");
                    break;
            }
        }

        Console.WriteLine("run ended");
    }

    private static string Describe(object? data) =>
        data is Exception e ? $"{e.GetBaseException().GetType().Name}: {e.GetBaseException().Message}" : $"{data}";
}
