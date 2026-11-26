using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Operations;

namespace Apsis.AgentFramework.Dotnet;

/// A state access: its scope (null: the executor's default scope) and key (null: not a compile-time constant).
internal sealed record StateAccess(bool Reads, bool Writes, string? Scope, string? Key);

/// What each class of the project sends, yields and accesses in state through `IWorkflowContext`, by runtime full name.
internal sealed class SourceFacts
{
    public Dictionary<string, SortedSet<string>> Sends { get; } = [];

    public Dictionary<string, SortedSet<string>> Yields { get; } = [];

    public Dictionary<string, List<StateAccess>> State { get; } = [];

    /// For each sent type (by spelling), its base classes and interfaces.
    public Dictionary<string, SortedSet<string>> Supertypes { get; } = [];

    /// Calls on the workflow context that the semantic model could not resolve; what they do is missing.
    public int UnresolvedCalls { get; private set; }

    public static SourceFacts Read(BuildResult build) =>
        FromSources(build.Sources.Select(f => (f, File.ReadAllText(f))), build.References, withPlatform: false);

    /// The facts of `sources` compiled against `references`, plus the platform assemblies with `withPlatform`.
    public static SourceFacts FromSources(IEnumerable<(string Path, string Text)> sources, IEnumerable<string> references, bool withPlatform = true)
    {
        var parse = new CSharpParseOptions(LanguageVersion.Latest);
        List<SyntaxTree> trees = sources.Select(s => CSharpSyntaxTree.ParseText(s.Text, parse, path: s.Path)).ToList();

        var metadata = new List<MetadataReference>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        IEnumerable<string> platform = withPlatform
            ? ((string)AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES")!).Split(Path.PathSeparator)
            : [];
        foreach (string dll in references.Concat(platform))
        {
            if (seen.Add(Path.GetFileNameWithoutExtension(dll)))
            {
                metadata.Add(MetadataReference.CreateFromFile(dll));
            }
        }

        CSharpCompilation compilation = CSharpCompilation.Create(
            "apsis-workflow-source",
            trees,
            metadata,
            new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary, nullableContextOptions: NullableContextOptions.Enable));

        var facts = new SourceFacts();
        foreach (SyntaxTree tree in trees)
        {
            SemanticModel model = compilation.GetSemanticModel(tree);
            // ordered by call end (a call completes after its arguments): in Update(k, Read(k) + 1) the read comes first
            foreach (InvocationExpressionSyntax call in tree.GetRoot().DescendantNodes().OfType<InvocationExpressionSyntax>().OrderBy(c => c.Span.End))
            {
                SymbolInfo info = model.GetSymbolInfo(call);
                if (info.Symbol is null && info.CandidateSymbols.OfType<IMethodSymbol>().Any(IsContextCall))
                {
                    facts.UnresolvedCalls++;
                }

                if (info.Symbol is not IMethodSymbol method || !IsContextCall(method)
                    || call.FirstAncestorOrSelf<TypeDeclarationSyntax>() is not TypeDeclarationSyntax owner
                    || model.GetDeclaredSymbol(owner) is not INamedTypeSymbol ownerType)
                {
                    continue;
                }

                string owningClass = RuntimeName(ownerType);
                if (StateAccessOf(method.Name) is (bool reads, bool writes))
                {
                    if (model.GetOperation(call) is IInvocationOperation operation)
                    {
                        string? Constant(string parameter) => operation.Arguments
                            .FirstOrDefault(a => a.Parameter?.Name == parameter)?.Value.ConstantValue is { HasValue: true, Value: string text } ? text : null;
                        bool named = operation.Arguments.Any(a => a.Parameter?.Name == "scopeName" && a.ArgumentKind != ArgumentKind.DefaultValue);
                        string? scope = named ? Constant("scopeName") ?? "?" : null;
                        string? key = method.Name == "ReadStateKeysAsync" ? null : Constant("key");
                        if (!facts.State.TryGetValue(owningClass, out List<StateAccess>? accesses))
                        {
                            facts.State[owningClass] = accesses = [];
                        }

                        accesses.Add(new StateAccess(reads, writes, scope, key));
                    }

                    continue;
                }

                Dictionary<string, SortedSet<string>> table = method.Name == "SendMessageAsync" ? facts.Sends : facts.Yields;
                ExpressionSyntax? message = call.ArgumentList.Arguments.FirstOrDefault()?.Expression;
                ITypeSymbol? type = method.IsGenericMethod ? method.TypeArguments[0] : message is null ? null : model.GetTypeInfo(message).Type;
                if (type is null || type.TypeKind == TypeKind.Error)
                {
                    continue;
                }

                if (!table.TryGetValue(owningClass, out SortedSet<string>? types))
                {
                    table[owningClass] = types = new SortedSet<string>(StringComparer.Ordinal);
                }

                types.Add(TypeNames.Spell(type));
                if (table == facts.Sends && TypeNames.Supertypes(type) is { Count: > 0 } supertypes)
                {
                    facts.Supertypes[TypeNames.Spell(type)] = supertypes;
                }
            }
        }

        return facts;
    }

    /// Whether a state method reads and whether it writes (`ReadOrInitStateAsync` writes when the key is absent).
    private static (bool Reads, bool Writes)? StateAccessOf(string method) => method switch
    {
        "ReadStateAsync" or "ReadStateKeysAsync" => (true, false),
        "ReadOrInitStateAsync" => (true, true),
        "QueueStateUpdateAsync" or "ClearStateAsync" => (false, true),
        _ => null,
    };

    /// A send, yield or state call on `IWorkflowContext`, including its extension methods.
    private static bool IsContextCall(IMethodSymbol method)
    {
        static bool IsContext(ITypeSymbol? t) =>
            t is not null && (t.Name == "IWorkflowContext" || t.AllInterfaces.Any(i => i.Name == "IWorkflowContext"));

        if (method.Name is not ("SendMessageAsync" or "YieldOutputAsync") && StateAccessOf(method.Name) is null)
        {
            return false;
        }

        IMethodSymbol definition = method.ReducedFrom ?? method;
        return IsContext(method.ContainingType)
            || (definition.IsExtensionMethod && definition.Parameters.Length > 0 && IsContext(definition.Parameters[0].Type));
    }

    /// The class's `Type.FullName` at run time (containing types joined by `+`).
    internal static string RuntimeName(INamedTypeSymbol type)
    {
        string name = type.MetadataName;
        for (INamedTypeSymbol? outer = type.ContainingType; outer is not null; outer = outer.ContainingType)
        {
            name = outer.MetadataName + "+" + name;
        }

        return type.ContainingNamespace.IsGlobalNamespace ? name : type.ContainingNamespace.ToDisplayString() + "." + name;
    }
}
