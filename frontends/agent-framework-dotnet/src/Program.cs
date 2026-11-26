// apsis front-end for Agent Framework workflows on the .NET SDK (Microsoft.Agents.AI.Workflows): builds the project
// and reads the built Workflow object without running it; what handlers send and yield through IWorkflowContext
// is read from the C# source with Roslyn.

using System.Text.Json;
using System.Text.Json.Nodes;

namespace Apsis.AgentFramework.Dotnet;

internal static class Program
{
    private const string Usage =
        "usage: apsis-agent-framework-dotnet <project.csproj>:<Type.Member> [-o ir.json] [--artifacts DIR]\n" +
        "  --artifacts DIR   build into DIR and keep it, so the next run builds incrementally (default: a temporary directory)";

    internal static int Main(string[] args)
    {
        string? output = null;
        string? spec = null;
        string? kept = null;
        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] is "-h" or "--help")
            {
                Console.WriteLine(Usage);
                return 0;
            }

            if (args[i] == "-o" && i + 1 < args.Length)
            {
                output = args[++i];
            }
            else if (args[i] == "--artifacts" && i + 1 < args.Length)
            {
                kept = Path.GetFullPath(args[++i]);
            }
            else
            {
                spec ??= args[i];
            }
        }

        int colon = spec?.LastIndexOf(':') ?? -1;
        if (spec is null || colon <= 0)
        {
            Console.Error.WriteLine(Usage);
            return 2;
        }

        string project = Path.GetFullPath(spec[..colon]);
        string entry = spec[(colon + 1)..];
        string artifacts = kept ?? Path.Combine(Path.GetTempPath(), "apsis-dotnet-" + Guid.NewGuid().ToString("N"));
        try
        {
            BuildResult build = ProjectBuild.Run(project, artifacts);
            object workflow = WorkflowLoader.Load(build.Assembly, entry, out bool shared);
            SourceFacts sources = SourceFacts.Read(build);
            if (sources.UnresolvedCalls > 0)
            {
                Console.Error.WriteLine(
                    $"apsis-agent-framework-dotnet: warning: {sources.UnresolvedCalls} calls on the workflow context in {project} could not be resolved; " +
                    "what they send or access is missing");
            }

            JsonObject ir = Extractor.Program(workflow, sources, spec, build.Assembly, shared);
            string json = ir.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
            if (output is null)
            {
                Console.WriteLine(json);
            }
            else
            {
                File.WriteAllText(output, json);
            }

            return 0;
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"apsis-agent-framework-dotnet: {e.GetBaseException().Message}");
            return 1;
        }
        finally
        {
            try
            {
                if (kept is null && Directory.Exists(artifacts))
                {
                    Directory.Delete(artifacts, recursive: true);
                }
            }
            catch (IOException)
            {
            }
        }
    }
}
