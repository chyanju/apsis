using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Agents.AI;
using Microsoft.Agents.AI.Workflows;
using Microsoft.Extensions.AI;

namespace WorkflowCustomAgentExecutorsSample;

public static class Case
{
    public static Workflow Build()
    {
        IChatClient chatClient = new CannedChatClient();

        var sloganWriter = new SloganWriterExecutor("SloganWriter", chatClient);
        var feedbackProvider = new FeedbackExecutor("FeedbackProvider", chatClient);

        return new WorkflowBuilder(sloganWriter)
            .AddEdge(sloganWriter, feedbackProvider)
            .AddEdge(feedbackProvider, sloganWriter)
            .WithOutputFrom(feedbackProvider)
            .Build();
    }
}

public sealed class SloganResult
{
    [JsonPropertyName("task")]
    public required string Task { get; set; }

    [JsonPropertyName("slogan")]
    public required string Slogan { get; set; }
}

public sealed class FeedbackResult
{
    [JsonPropertyName("comments")]
    public string Comments { get; set; } = string.Empty;

    [JsonPropertyName("rating")]
    public int Rating { get; set; }

    [JsonPropertyName("actions")]
    public string Actions { get; set; } = string.Empty;
}

internal sealed class SloganGeneratedEvent(SloganResult sloganResult) : WorkflowEvent(sloganResult)
{
    public override string ToString() => $"Slogan: {sloganResult.Slogan}";
}

internal sealed class SloganWriterExecutor : Executor
{
    private readonly AIAgent _agent;
    private AgentSession? _session;

    public SloganWriterExecutor(string id, IChatClient chatClient) : base(id)
    {
        ChatClientAgentOptions agentOptions = new()
        {
            ChatOptions = new()
            {
                Instructions = "You are a professional slogan writer. You will be given a task to create a slogan.",
                ResponseFormat = ChatResponseFormat.ForJsonSchema<SloganResult>()
            }
        };

        this._agent = new ChatClientAgent(chatClient, agentOptions);
    }

    protected override ProtocolBuilder ConfigureProtocol(ProtocolBuilder protocolBuilder)
    {
        protocolBuilder.ConfigureRoutes(routeBuilder => routeBuilder.AddHandler<string, SloganResult>(this.HandleAsync).AddHandler<FeedbackResult, SloganResult>(this.HandleAsync));
        return protocolBuilder;
    }

    public async ValueTask<SloganResult> HandleAsync(string message, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        this._session ??= await this._agent.CreateSessionAsync(cancellationToken);

        var result = await this._agent.RunAsync(message, this._session, cancellationToken: cancellationToken);

        var sloganResult = JsonSerializer.Deserialize<SloganResult>(result.Text) ?? throw new InvalidOperationException("Failed to deserialize slogan result.");

        await context.AddEventAsync(new SloganGeneratedEvent(sloganResult), cancellationToken);
        return sloganResult;
    }

    public async ValueTask<SloganResult> HandleAsync(FeedbackResult message, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        var feedbackMessage = $"""
            Here is the feedback on your previous slogan:
            Comments: {message.Comments}
            Rating: {message.Rating}
            Suggested Actions: {message.Actions}

            Please use this feedback to improve your slogan.
            """;

        var result = await this._agent.RunAsync(feedbackMessage, this._session, cancellationToken: cancellationToken);
        var sloganResult = JsonSerializer.Deserialize<SloganResult>(result.Text) ?? throw new InvalidOperationException("Failed to deserialize slogan result.");

        await context.AddEventAsync(new SloganGeneratedEvent(sloganResult), cancellationToken);
        return sloganResult;
    }
}

internal sealed class FeedbackEvent(FeedbackResult feedbackResult) : WorkflowEvent(feedbackResult)
{
    private readonly JsonSerializerOptions _options = new() { WriteIndented = true };
    public override string ToString() => $"Feedback:\n{JsonSerializer.Serialize(feedbackResult, this._options)}";
}

[YieldsOutput(typeof(string))]
[SendsMessage(typeof(FeedbackResult))]
internal sealed class FeedbackExecutor : Executor<SloganResult>
{
    private readonly AIAgent _agent;
    private AgentSession? _session;

    public int MinimumRating { get; init; } = 8;

    public int MaxAttempts { get; init; } = 3;

    private int _attempts;

    public FeedbackExecutor(string id, IChatClient chatClient) : base(id)
    {
        ChatClientAgentOptions agentOptions = new()
        {
            ChatOptions = new()
            {
                Instructions = "You are a professional editor. You will be given a slogan and the task it is meant to accomplish.",
                ResponseFormat = ChatResponseFormat.ForJsonSchema<FeedbackResult>()
            }
        };

        this._agent = new ChatClientAgent(chatClient, agentOptions);
    }

    public override async ValueTask HandleAsync(SloganResult message, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        this._session ??= await this._agent.CreateSessionAsync(cancellationToken);

        var sloganMessage = $"""
            Here is a slogan for the task '{message.Task}':
            Slogan: {message.Slogan}
            Please provide feedback on this slogan, including comments, a rating from 1 to 10, and suggested actions for improvement.
            """;

        var response = await this._agent.RunAsync(sloganMessage, this._session, cancellationToken: cancellationToken);
        var feedback = JsonSerializer.Deserialize<FeedbackResult>(response.Text) ?? throw new InvalidOperationException("Failed to deserialize feedback.");

        await context.AddEventAsync(new FeedbackEvent(feedback), cancellationToken);

        if (feedback.Rating >= this.MinimumRating)
        {
            await context.YieldOutputAsync($"The following slogan was accepted:\n\n{message.Slogan}", cancellationToken);
            return;
        }

        if (this._attempts >= this.MaxAttempts)
        {
            await context.YieldOutputAsync($"The slogan was rejected after {this.MaxAttempts} attempts. Final slogan:\n\n{message.Slogan}", cancellationToken);
            return;
        }

        await context.SendMessageAsync(feedback, cancellationToken: cancellationToken);
        this._attempts++;
    }
}

internal sealed class CannedChatClient : IChatClient
{
    private const string FirstSlogan = "Electric adventures for everyone.";
    private const string RevisedSlogan = "Big fun, small price: the electric SUV for every road.";

    public Task<ChatResponse> GetResponseAsync(IEnumerable<ChatMessage> messages, ChatOptions? options = null, CancellationToken cancellationToken = default)
        => Task.FromResult(new ChatResponse(new ChatMessage(ChatRole.Assistant, Reply(messages))));

    public async IAsyncEnumerable<ChatResponseUpdate> GetStreamingResponseAsync(
        IEnumerable<ChatMessage> messages,
        ChatOptions? options = null,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        await Task.Yield();
        yield return new ChatResponseUpdate(ChatRole.Assistant, Reply(messages));
    }

    public object? GetService(Type serviceType, object? serviceKey = null) => null;

    public void Dispose()
    {
    }

    private static string Reply(IEnumerable<ChatMessage> messages)
    {
        List<ChatMessage> user = messages.Where(m => m.Role == ChatRole.User).ToList();
        string last = user.LastOrDefault()?.Text ?? string.Empty;
        if (last.StartsWith("Here is a slogan", StringComparison.Ordinal))
        {
            return last.Contains(RevisedSlogan, StringComparison.Ordinal)
                ? JsonSerializer.Serialize(new FeedbackResult { Comments = "Clear, upbeat and about the price.", Rating = 9, Actions = "None." })
                : JsonSerializer.Serialize(new FeedbackResult { Comments = "Generic; it says nothing about the price.", Rating = 5, Actions = "Say that the SUV is affordable." });
        }

        string task = user.FirstOrDefault()?.Text ?? string.Empty;
        return last.StartsWith("Here is the feedback", StringComparison.Ordinal)
            ? JsonSerializer.Serialize(new SloganResult { Task = task, Slogan = RevisedSlogan })
            : JsonSerializer.Serialize(new SloganResult { Task = task, Slogan = FirstSlogan });
    }
}
