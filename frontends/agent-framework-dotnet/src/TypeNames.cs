using Microsoft.CodeAnalysis;

namespace Apsis.AgentFramework.Dotnet;

/// Spells runtime types and Roslyn symbols alike in the IR type grammar, without namespaces, so the two compare equal.
internal static class TypeNames
{
    public static string Spell(Type t)
    {
        if (t.IsArray)
        {
            return Spell(t.GetElementType()!) + "[]";
        }

        if (Nullable.GetUnderlyingType(t) is Type underlying)
        {
            return $"Optional[{Spell(underlying)}]";
        }

        if (t.IsGenericType)
        {
            string name = t.Name[..t.Name.IndexOf('`')];
            return $"{Canonical(name)}[{string.Join(", ", t.GetGenericArguments().Select(Spell))}]";
        }

        return Canonical(t.Name);
    }

    public static string Spell(ITypeSymbol t)
    {
        switch (t)
        {
            case IArrayTypeSymbol array:
                return Spell(array.ElementType) + "[]";
            case INamedTypeSymbol named when named.OriginalDefinition.SpecialType == SpecialType.System_Nullable_T:
                return $"Optional[{Spell(named.TypeArguments[0])}]";
            case INamedTypeSymbol named when named.IsGenericType:
                string name = named.MetadataName[..named.MetadataName.IndexOf('`')];
                return $"{Canonical(name)}[{string.Join(", ", named.TypeArguments.Select(Spell))}]";
            default:
                return Canonical(t.MetadataName);
        }
    }

    /// The base classes and interfaces of `t`, without those of `System` namespaces (a workflow does not dispatch on them).
    public static SortedSet<string> Supertypes(Type t)
    {
        var all = new SortedSet<string>(StringComparer.Ordinal);
        for (Type? b = t.BaseType; b is not null; b = b.BaseType)
        {
            if (!IsPlatform(b.Namespace))
            {
                all.Add(Spell(b));
            }
        }

        foreach (Type i in t.GetInterfaces().Where(i => !IsPlatform(i.Namespace)))
        {
            all.Add(Spell(i));
        }

        return all;
    }

    /// The same for a type of the source.
    public static SortedSet<string> Supertypes(ITypeSymbol t)
    {
        static bool Platform(INamedTypeSymbol s) => s.ContainingNamespace is { IsGlobalNamespace: false } ns && IsPlatform(ns.ToDisplayString());

        var all = new SortedSet<string>(StringComparer.Ordinal);
        for (INamedTypeSymbol? b = t.BaseType; b is not null; b = b.BaseType)
        {
            if (!Platform(b))
            {
                all.Add(Spell(b));
            }
        }

        foreach (INamedTypeSymbol i in t.AllInterfaces.Where(i => !Platform(i)))
        {
            all.Add(Spell(i));
        }

        return all;
    }

    private static bool IsPlatform(string? ns) => ns == "System" || (ns?.StartsWith("System.", StringComparison.Ordinal) ?? false);

    private static string Canonical(string name) => name switch
    {
        "String" => "string",
        "Int32" => "int",
        "Int64" => "long",
        "Boolean" => "bool",
        "Double" => "double",
        "Single" => "float",
        "Decimal" => "decimal",
        "Object" => "object",
        "Byte" => "byte",
        "Char" => "char",
        "List" => "list",
        _ => name,
    };
}
