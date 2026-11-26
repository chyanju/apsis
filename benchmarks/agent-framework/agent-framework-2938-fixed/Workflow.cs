using System.Runtime.CompilerServices;
using Microsoft.Agents.AI;
using Microsoft.Agents.AI.Workflows;
using Microsoft.Extensions.AI;

namespace AgentsInWorkflows;

public static class Case
{
    public static Workflow Build()
    {
        IChatClient chatClient = new CannedChatClient();

        var frenchAgent = new ChatClientAgent(chatClient, instructions: $"You are a translation assistant that translates the provided text to french.");
        var spanishAgent = new ChatClientAgent(chatClient, instructions: $"You are a translation assistant that translates the provided text to spanish.");
        var englishAgent = new ChatClientAgent(chatClient, instructions: $"You are a translation assistant that translates the provided text to english.");

        var workflow = AgentWorkflowBuilder.BuildSequential(
            new List<AIAgent> { frenchAgent, spanishAgent, englishAgent }
            );

        return workflow;
    }
}

internal sealed class CannedChatClient : IChatClient
{
    public Task<ChatResponse> GetResponseAsync(IEnumerable<ChatMessage> messages, ChatOptions? options = null, CancellationToken cancellationToken = default)
        => Task.FromResult(new ChatResponse(new ChatMessage(ChatRole.Assistant, Reply(messages, options))));

    public async IAsyncEnumerable<ChatResponseUpdate> GetStreamingResponseAsync(
        IEnumerable<ChatMessage> messages,
        ChatOptions? options = null,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        await Task.Yield();
        yield return new ChatResponseUpdate(ChatRole.Assistant, Reply(messages, options));
    }

    public object? GetService(Type serviceType, object? serviceKey = null) => null;

    public void Dispose()
    {
    }

    private static string Reply(IEnumerable<ChatMessage> messages, ChatOptions? options)
    {
        string instructions = options?.Instructions
            ?? string.Join("\n", messages.Where(m => m.Role == ChatRole.System).Select(m => m.Text));
        return instructions switch
        {
            _ when instructions.EndsWith("to french.", StringComparison.Ordinal) => "Traduisez ce message : Bonjour le monde !",
            _ when instructions.EndsWith("to spanish.", StringComparison.Ordinal) => "Traduce este mensaje: ¡Hola Mundo!",
            _ => "Translate this message: Hello World!",
        };
    }
}
