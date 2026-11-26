using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Xunit;

namespace Apsis.AgentFramework.Dotnet.Tests;

public class TypeNamesTests
{
    private const string Probe = """
        using System.Collections.Generic;
        public class Probe
        {
            public string F0 = "";
            public int F1;
            public List<string> F2 = new();
            public int? F3;
            public string[] F4 = [];
            public Dictionary<string, List<int>> F5 = new();
            public IEnumerable<object> F6 = [];
        }
        """;

    [Fact]
    public void RuntimeTypesAndSourceSymbolsAreSpelledAlike()
    {
        Type[] runtime = [typeof(string), typeof(int), typeof(List<string>), typeof(int?), typeof(string[]), typeof(Dictionary<string, List<int>>), typeof(IEnumerable<object>)];
        string[] expected = ["string", "int", "list[string]", "Optional[int]", "string[]", "Dictionary[string, list[int]]", "IEnumerable[object]"];

        IEnumerable<MetadataReference> platform = ((string)AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES")!)
            .Split(Path.PathSeparator).Select(p => MetadataReference.CreateFromFile(p));
        CSharpCompilation compilation = CSharpCompilation.Create("probe", [CSharpSyntaxTree.ParseText(Probe)], platform);
        INamedTypeSymbol probe = compilation.GetTypeByMetadataName("Probe")!;

        for (int i = 0; i < runtime.Length; i++)
        {
            var field = (IFieldSymbol)probe.GetMembers($"F{i}").Single();
            Assert.Equal(expected[i], TypeNames.Spell(runtime[i]));
            Assert.Equal(expected[i], TypeNames.Spell(field.Type));
        }
    }

    [Fact]
    public void ATypeIsAlsoItsBaseClassesAndInterfacesOutsideThePlatform()
    {
        Assert.Equal(["Base"], TypeNames.Supertypes(typeof(Derived)));
        Assert.Empty(TypeNames.Supertypes(typeof(string)));
        Assert.Empty(TypeNames.Supertypes(typeof(List<Derived>)));
    }
}
