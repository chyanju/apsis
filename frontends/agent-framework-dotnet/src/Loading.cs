using System.Diagnostics;
using System.Reflection;
using System.Runtime.Loader;
using System.Text.Json;

namespace Apsis.AgentFramework.Dotnet;

/// A built project: its assembly and the source files and references the compiler was given.
internal sealed record BuildResult(string Assembly, IReadOnlyList<string> Sources, IReadOnlyList<string> References);

/// Builds a project with `dotnet build` into an artifacts directory and reads back its `Compile` and `ReferencePath` items.
internal static class ProjectBuild
{
    public static BuildResult Run(string project, string artifacts)
    {
        string dotnet = Environment.GetEnvironmentVariable("DOTNET_HOST_PATH") ?? "dotnet";
        var psi = new ProcessStartInfo(dotnet)
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        string[] args =
        [
            "build", project, "-c", "Release", "--artifacts-path", artifacts, "--nologo",
            "-t:Build", "-getItem:Compile", "-getItem:ReferencePath", "-getProperty:TargetPath",
        ];
        foreach (string a in args)
        {
            psi.ArgumentList.Add(a);
        }

        string assets = Path.Combine(artifacts, "obj", Path.GetFileNameWithoutExtension(project), "project.assets.json");
        if (File.Exists(assets) && File.GetLastWriteTimeUtc(assets) >= File.GetLastWriteTimeUtc(project))
        {
            psi.ArgumentList.Add("--no-restore");
        }

        using Process p = Process.Start(psi)!;
        Task<string> stdout = p.StandardOutput.ReadToEndAsync();
        Task<string> stderr = p.StandardError.ReadToEndAsync();
        p.WaitForExit();
        if (p.ExitCode != 0)
        {
            throw new InvalidOperationException($"dotnet build {project} failed:\n{stdout.Result}{stderr.Result}");
        }

        using JsonDocument report = JsonDocument.Parse(stdout.Result);
        JsonElement items = report.RootElement.GetProperty("Items");
        List<string> Paths(string item) => items.TryGetProperty(item, out JsonElement list)
            ? list.EnumerateArray().Select(i => i.GetProperty("FullPath").GetString()!).ToList()
            : [];
        string assembly = report.RootElement.GetProperty("Properties").GetProperty("TargetPath").GetString()!;
        return new BuildResult(assembly, Paths("Compile"), Paths("ReferencePath"));
    }
}

/// Loads a project's assembly with the dependencies of its build output, so the referenced SDK release is used.
internal sealed class ProjectLoadContext(string assembly) : AssemblyLoadContext("apsis-workflow")
{
    private readonly AssemblyDependencyResolver _resolver = new(assembly);

    protected override Assembly? Load(AssemblyName name)
    {
        string? path = this._resolver.ResolveAssemblyToPath(name);
        return path is null ? null : this.LoadFromAssemblyPath(path);
    }
}

internal static class WorkflowLoader
{
    private const BindingFlags Static = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;

    /// Returns the workflow the static member `entry` constructs; `shared`: a method returned the same object twice.
    public static object Load(string assemblyPath, string entry, out bool shared)
    {
        shared = false;
        var context = new ProjectLoadContext(assemblyPath);
        Assembly assembly = context.LoadFromAssemblyPath(assemblyPath);
        int dot = entry.LastIndexOf('.');
        if (dot <= 0)
        {
            throw new ArgumentException($"entry `{entry}` is not of the form Type.Member");
        }

        string typeName = entry[..dot];
        string member = entry[(dot + 1)..];
        Type type = assembly.GetType(typeName)
            ?? assembly.GetTypes().FirstOrDefault(t => t.Name == typeName)
            ?? throw new InvalidOperationException($"no type `{typeName}` in {assembly.GetName().Name}");

        object? value;
        if (type.GetProperty(member, Static) is PropertyInfo property)
        {
            value = property.GetValue(null);
        }
        else if (type.GetField(member, Static) is FieldInfo field)
        {
            value = field.GetValue(null);
        }
        else if (type.GetMethod(member, Static, Type.EmptyTypes) is MethodInfo method)
        {
            value = method.Invoke(null, null);
            object? first = Reflect.Await(value);
            if (first is not null && Reflect.IsA(first.GetType(), "Microsoft.Agents.AI.Workflows.Workflow"))
            {
                try
                {
                    shared = ReferenceEquals(first, Reflect.Await(method.Invoke(null, null)));
                }
                catch (Exception)
                {
                    // a method that cannot be called twice tells nothing about sharing
                }
            }

            value = first;
        }
        else
        {
            throw new InvalidOperationException($"`{type.FullName}` has no static member `{member}`");
        }

        value = Reflect.Await(value);
        if (value is not null && value.GetType().Name == "WorkflowBuilder")
        {
            MethodInfo build = value.GetType().GetMethods().First(m => m.Name == "Build");
            value = Reflect.Await(build.Invoke(value, build.GetParameters().Select(p => p.DefaultValue).ToArray()));
        }

        if (value is null || !Reflect.IsA(value.GetType(), "Microsoft.Agents.AI.Workflows.Workflow"))
        {
            throw new InvalidOperationException($"`{entry}` is a {value?.GetType().FullName ?? "null"}, not a Workflow");
        }

        return value;
    }
}

/// Reflection helpers that read members by name, so one front-end reads any release of the SDK.
internal static class Reflect
{
    private const BindingFlags Instance = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;

    public static object? Get(object? target, string name)
    {
        for (Type? t = target?.GetType(); t is not null; t = t.BaseType)
        {
            if (t.GetProperty(name, Instance | BindingFlags.DeclaredOnly) is PropertyInfo p)
            {
                return p.GetValue(target);
            }

            if (t.GetField(name, Instance | BindingFlags.DeclaredOnly) is FieldInfo f)
            {
                return f.GetValue(target);
            }
        }

        return null;
    }

    public static bool Has(object? target, string name)
    {
        for (Type? t = target?.GetType(); t is not null; t = t.BaseType)
        {
            if (t.GetProperty(name, Instance | BindingFlags.DeclaredOnly) is not null || t.GetField(name, Instance | BindingFlags.DeclaredOnly) is not null)
            {
                return true;
            }
        }

        return false;
    }

    /// The first instance field value of `target` whose runtime type is or derives from `typeFullName`.
    public static object? FieldOfType(object? target, string typeFullName)
    {
        for (Type? t = target?.GetType(); t is not null; t = t.BaseType)
        {
            foreach (FieldInfo f in t.GetFields(Instance | BindingFlags.DeclaredOnly))
            {
                if (f.GetValue(target) is object value && IsA(value.GetType(), typeFullName))
                {
                    return value;
                }
            }
        }

        return null;
    }

    public static object? Call(object? target, string name)
    {
        for (Type? t = target?.GetType(); t is not null; t = t.BaseType)
        {
            if (t.GetMethod(name, Instance | BindingFlags.DeclaredOnly, Type.EmptyTypes) is MethodInfo m)
            {
                return m.Invoke(target, null);
            }
        }

        return null;
    }

    public static object? Await(object? value)
    {
        if (value is null)
        {
            return null;
        }

        Type type = value.GetType();
        if (type.IsGenericType && type.GetGenericTypeDefinition().FullName == "System.Threading.Tasks.ValueTask`1")
        {
            value = type.GetMethod("AsTask")!.Invoke(value, null);
        }

        if (value is Task task)
        {
            task.GetAwaiter().GetResult();
            return task.GetType().GetProperty("Result")?.GetValue(task);
        }

        return value;
    }

    public static bool IsA(Type type, string fullName)
    {
        for (Type? t = type; t is not null; t = t.BaseType)
        {
            if (t.FullName == fullName)
            {
                return true;
            }
        }

        return false;
    }
}
