using Microsoft.Agents.AI.Workflows;
using Microsoft.Extensions.AI;

namespace AgentFramework3766;

public static class Run
{
    private static int s_min = 0, s_max = 100, s_guess = 0;

    public static async Task Main()
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        List<ChatMessage> input = [new(ChatRole.User, "I want to play the number guessing game.")];
        await using StreamingRun run = await InProcessExecution.StreamAsync(Case.Build(), input, cancellationToken: timeout.Token);
        await run.TrySendMessageAsync(new TurnToken(emitEvents: true));

        ExternalRequest? inAgentResponse = null;
        await foreach (WorkflowEvent evt in run.WatchStreamAsync(timeout.Token))
        {
            inAgentResponse = await PrintAsync(run, evt) ?? inAgentResponse;
        }

        if (inAgentResponse is not null)
        {
            int guess = NextGuess(inAgentResponse);
            await run.SendResponseAsync(inAgentResponse.CreateResponse(guess));
            Console.WriteLine($"answer   {guess} to {inAgentResponse.PortInfo.PortId} with SendResponseAsync, run status {await run.GetStatusAsync()}");
            await foreach (WorkflowEvent evt in run.WatchStreamAsync(timeout.Token))
            {
                await PrintAsync(run, evt);
            }
        }

        if (timeout.IsCancellationRequested)
        {
            Console.WriteLine($"timed out, run status {await run.GetStatusAsync()}");
        }

        Console.WriteLine("run ended");
    }

    private static async ValueTask<ExternalRequest?> PrintAsync(StreamingRun run, WorkflowEvent evt)
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
                Console.WriteLine($"output   {Describe(e.Data)}");
                break;
            case RequestInfoEvent e:
                int guess = NextGuess(e.Request);
                Console.WriteLine($"request  {e.Request.PortInfo.PortId} ({e.Request.DataAs<NumberSignal>()}): answered {guess}");
                await run.SendResponseAsync(e.Request.CreateResponse(guess));
                break;

            case AgentResponseUpdateEvent { Update.RawRepresentation: ExecutorInvokedEvent inner } e:
                Console.WriteLine($"invoked  {inner.ExecutorId} (inside {e.ExecutorId})");
                break;
            case AgentResponseUpdateEvent { Update.RawRepresentation: RequestInfoEvent inner } e:
                Console.WriteLine($"update   {e.ExecutorId}: function call {inner.Request.PortInfo.PortId} ({inner.Request.DataAs<NumberSignal>()}), not a RequestInfoEvent");
                return inner.Request;
        }

        return null;
    }

    private static int NextGuess(ExternalRequest request)
    {
        NumberSignal signal = request.DataAs<NumberSignal>();
        if (signal == NumberSignal.Above)
        {
            s_max = s_guess - 1;
        }
        else if (signal == NumberSignal.Below)
        {
            s_min = s_guess + 1;
        }

        s_guess = (s_min + s_max) / 2;
        return s_guess;
    }

    private static string Describe(object? data) => data switch
    {
        Exception ex => $"{ex.GetBaseException().GetType().Name}: {ex.GetBaseException().Message}",
        IEnumerable<ChatMessage> messages => string.Join(" | ", messages.Where(m => m.Contents.Count > 0).Select(Describe)),
        _ => $"{data}",
    };

    private static string Describe(ChatMessage message) =>
        $"{message.Role}{(message.AuthorName is null ? "" : $" {message.AuthorName}")}: " + string.Join(", ", message.Contents.Select(c => c switch
        {
            TextContent t => t.Text,
            FunctionCallContent f => $"call {f.Name}",
            FunctionResultContent r => $"result {r.Result}",
            _ => c.GetType().Name,
        }));
}
