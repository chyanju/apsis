using System.Collections;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Apsis.AgentFramework.Dotnet;

/// Reads a built `Microsoft.Agents.AI.Workflows.Workflow` into the apsis IR (crates/apsis-ir): one IR workflow for
/// it and one for every workflow it embeds.
internal static class Extractor
{
    /// What the engine's agent host sends without declaring it: the response's messages and the turn token.
    private static readonly string[] AgentHostSends = ["list[ChatMessage]", "TurnToken"];

    /// What SDK executors send and yield where they declare neither (before 1.0.0-rc1), read from the SDK source.
    private static readonly Dictionary<string, (string[] Sends, string[] Yields)> SdkExecutorModels = new(StringComparer.Ordinal)
    {
        ["Microsoft.Agents.AI.Workflows.Specialized.AgentRunStreamingExecutor"] = (["list[ChatMessage]"], []),
        ["Microsoft.Agents.AI.Workflows.AgentWorkflowBuilder+OutputMessagesExecutor"] = ([], ["list[ChatMessage]"]),
        ["Microsoft.Agents.AI.Workflows.OutputMessagesExecutor"] = ([], ["list[ChatMessage]"]),
    };

    /// What the engine's agent host accepts: the chat protocol, when its handlers cannot be read outside a run.
    private static readonly string[] AgentHostAccepts = ["ChatMessage", "ChatMessage[]", "IEnumerable[ChatMessage]", "TurnToken", "list[ChatMessage]"];

    public static JsonObject Program(object workflow, SourceFacts sources, string provenance, string? assembly = null, bool shared = false)
    {
        string? version = (assembly is null ? null : PackageVersion(assembly, "Microsoft.Agents.AI.Workflows"))
            ?? workflow.GetType().Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion?.Split('+')[0];
        var program = new ProgramBuilder(sources, version, provenance);
        program.Add(workflow, (string?)Reflect.Get(workflow, "Name") ?? "main");
        if (shared)
        {
            program.Workflows[0]!["attrs"] = new JsonObject { ["shared_workflow"] = "true" };
        }

        return new JsonObject { ["workflows"] = new JsonArray(program.Workflows.Select(w => (JsonNode)w!).ToArray()) };
    }

    /// An IR workflow being written.
    private sealed class Extracted(string id)
    {
        public string Id { get; } = id;

        public SortedSet<string> Yields { get; } = new(StringComparer.Ordinal);

        public bool YieldsKnown { get; set; } = true;

        public List<string> RequestPorts { get; } = [];
    }

    private sealed class ProgramBuilder(SourceFacts sources, string? version, string provenance)
    {
        private readonly Dictionary<object, Extracted> _byInstance = new(ReferenceEqualityComparer.Instance);
        private readonly HashSet<string> _ids = [];

        public List<JsonObject?> Workflows { get; } = [];

        /// The IR workflow of `workflow`, written on first sight; one per object.
        public Extracted Add(object workflow, string preferredId)
        {
            if (this._byInstance.TryGetValue(workflow, out Extracted? known))
            {
                return known;
            }

            string id = preferredId;
            for (int i = 2; !this._ids.Add(id); i++)
            {
                id = $"{preferredId}_{i}";
            }

            var extracted = new Extracted(id);
            this._byInstance[workflow] = extracted;
            int slot = this.Workflows.Count;
            this.Workflows.Add(null);
            this.Workflows[slot] = this.Write(workflow, extracted);
            return extracted;
        }

        private JsonObject Write(object workflow, Extracted info)
        {
            var outputIds = new HashSet<string>(Strings(Reflect.Get(workflow, "OutputExecutors")));
            // `ExecutorBindings` from release 1.0.0-preview.251104.1, `Registrations` before it
            object table = Reflect.Get(workflow, "ExecutorBindings") ?? Reflect.Get(workflow, "Registrations")
                ?? throw new InvalidOperationException("the workflow has neither ExecutorBindings nor Registrations");
            List<(string Id, object Binding)> bindings = ((IEnumerable)table).Cast<object>()
                .Select(pair => ((string)Reflect.Get(pair, "Key")!, Reflect.Get(pair, "Value")!))
                .ToList();
            Dictionary<string, string> ids = StableIds(bindings);
            string Id(string engineId) => ids.GetValueOrDefault(engineId, engineId);
            // from 1.0.0-rc1 (`ProtocolDescriptor` has `Sends`) a handler also receives derived types
            bool byInstance = workflow.GetType().Assembly.GetType("Microsoft.Agents.AI.Workflows.ProtocolDescriptor")?.GetProperty("Sends") is not null;

            JsonArray edges = Edges(workflow, Id, out HashSet<string> barriers);
            var fedBy = edges.Select(e => (string)e!["to"]!["node"]!).GroupBy(t => t).ToDictionary(g => g.Key, g => g.Count());
            var nodes = new JsonArray();
            var hosts = new List<(JsonObject Node, Extracted Sub)>();
            var state = new List<(string Executor, StateAccess Access)>();
            foreach ((string engineId, object binding) in bindings)
            {
                string id = Id(engineId);
                bool isOutput = outputIds.Contains(engineId);
                Type executorType = (Type)Reflect.Get(binding, "ExecutorType")!;
                object? raw = Reflect.Get(binding, "RawValue") ?? Reflect.Get(binding, "RawExecutorishData");
                var facts = new NodeFacts();
                object? executor = null;
                try
                {
                    executor = Instance(binding, engineId);
                    if (executor is not null)
                    {
                        facts.Read(executor, isOutput);
                    }
                }
                catch (Exception e)
                {
                    // Some executors of the SDK configure their handlers only inside a run.
                    facts.Unread = true;
                    Console.Error.WriteLine($"apsis-agent-framework-dotnet: warning: the handlers of `{id}` cannot be read outside a run: {e.GetBaseException().Message}");
                }

                string kind = "executor";
                Extracted? sub = null;
                bool forwardsRequests = false;
                bool sdkType = executorType.Assembly.GetName().Name?.StartsWith("Microsoft.Agents.AI", StringComparison.Ordinal) == true;

                // a bound agent, or the agent an SDK executor runs (handoff); project executors stay executors
                object? agent = raw is not null && Reflect.IsA(raw.GetType(), "Microsoft.Agents.AI.AIAgent")
                    ? raw
                    : sdkType ? Reflect.FieldOfType(executor, "Microsoft.Agents.AI.AIAgent") : null;
                if (agent is not null)
                {
                    kind = "agent";

                    // the agent host the engine binds an agent with; a handoff executor sends its own messages
                    if (ReferenceEquals(agent, raw))
                    {
                        if (facts.DeclaredSends.Count == 0)
                        {
                            facts.Sends.UnionWith(AgentHostSends);
                        }

                        if (facts.Unread)
                        {
                            facts.Accepts.UnionWith(AgentHostAccepts);
                        }
                    }

                    // `Workflow.AsAgent()`: its requests become function calls, so no parent step answers them
                    if (Reflect.FieldOfType(agent, "Microsoft.Agents.AI.Workflows.Workflow") is object inner)
                    {
                        sub = this.Add(inner, (string?)Reflect.Get(inner, "Name") ?? id);
                    }
                }
                else if (raw is not null && Reflect.IsA(raw.GetType(), "Microsoft.Agents.AI.Workflows.Workflow"))
                {
                    kind = "subflow";
                    forwardsRequests = true;
                    sub = this.Add(raw, (string?)Reflect.Get(raw, "Name") ?? id);
                    facts.Sends.UnionWith(sub.Yields);
                    if (sub.RequestPorts.Count > 0)
                    {
                        facts.Sends.Add("ExternalRequest");
                    }

                    if (isOutput)
                    {
                        facts.Yields.UnionWith(sub.Yields);
                    }
                }
                else if (raw is not null && Reflect.IsA(raw.GetType(), "Microsoft.Agents.AI.Workflows.RequestPort"))
                {
                    kind = "human-input";
                    info.RequestPorts.Add(id);

                    if (Reflect.Get(raw, "Request") is Type request)
                    {
                        facts.Accepts.Add(TypeNames.Spell(request));
                    }

                    if (Reflect.Get(raw, "Response") is Type response)
                    {
                        facts.Sends.Add(TypeNames.Spell(response));
                    }
                }

                string key = executorType.FullName ?? executorType.Name;
                if (!facts.DeclaresProtocol)
                {
                    // a chat-protocol executor passes the turn token on after its turn (`ChatProtocolExecutor.TakeTurnAsync`)
                    if (Reflect.IsA(executorType, "Microsoft.Agents.AI.Workflows.ChatProtocolExecutor"))
                    {
                        facts.Sends.Add("TurnToken");
                    }

                    if (sdkType && SdkExecutorModels.TryGetValue(key, out var model))
                    {
                        facts.Sends.UnionWith(model.Sends);
                        if (isOutput)
                        {
                            facts.Yields.UnionWith(model.Yields);
                        }
                    }
                }

                if (sources.Sends.TryGetValue(key, out SortedSet<string>? sent))
                {
                    facts.Sends.UnionWith(sent);
                }

                if (isOutput && !facts.DeclaresProtocol && sources.Yields.TryGetValue(key, out SortedSet<string>? yielded))
                {
                    facts.Yields.UnionWith(yielded);
                }

                foreach (StateAccess access in sources.State.GetValueOrDefault(key) ?? [])
                {
                    state.Add((id, access));
                }

                // a project executor's yields are read from its source
                bool yieldsKnown = !facts.Unread && (facts.DeclaresProtocol || !sdkType || facts.Yields.Count > 0 || (kind == "subflow" && sub!.YieldsKnown));
                if (isOutput)
                {
                    info.Yields.UnionWith(facts.Yields);
                    info.YieldsKnown &= yieldsKnown;
                }

                var attrs = new JsonObject();
                if (yieldsKnown)
                {
                    attrs["workflow_output_types"] = string.Join(", ", facts.Yields);
                }
                else if (isOutput)
                {
                    attrs["yields_unknown"] = "true";
                }

                if (kind == "human-input")
                {
                    attrs["request_port"] = "true";
                }

                // the engine checks the sends of every executor; those of the project are the ones its source shows
                if (facts.DeclaresProtocol && kind == "executor" && sources.Sends.ContainsKey(key))
                {
                    attrs["declared_sends"] = string.Join(", ", facts.DeclaredSends);
                }

                if (byInstance)
                {
                    foreach (string t in facts.Sends)
                    {
                        if ((facts.Supertypes.GetValueOrDefault(t) ?? sources.Supertypes.GetValueOrDefault(t)) is { Count: > 0 } supertypes)
                        {
                            attrs[$"supertypes:{t}"] = string.Join(", ", supertypes);
                        }
                    }
                }

                if (fedBy.GetValueOrDefault(id) >= 2)
                {
                    attrs["fan_in_delivery"] = "each";
                }

                if (barriers.Contains(id))
                {
                    attrs["barrier_join"] = "true";
                }

                var node = new JsonObject
                {
                    ["id"] = id,
                    ["type_name"] = key,
                    ["kind"] = kind,
                    ["inputs"] = Sockets(facts.Accepts, input: true),
                    ["outputs"] = Sockets(facts.Sends, input: false),
                    ["attrs"] = attrs,
                };
                if (kind == "agent" && Reflect.Get(raw, "Name") is string agentName)
                {
                    node["name"] = agentName;
                }

                if (sub is not null)
                {
                    node["subflow_ref"] = new JsonObject
                    {
                        ["workflow"] = sub.Id,
                        ["in_bindings"] = new JsonArray(),
                        ["out_bindings"] = new JsonArray(),
                    };
                    if (forwardsRequests)
                    {
                        hosts.Add((node, sub));
                    }
                }

                nodes.Add(node);
            }

            BindRequestPorts(hosts, nodes, edges);
            JsonArray channels = Channels(state, out Dictionary<string, SortedSet<string>> readsFirst);
            foreach (JsonObject node in nodes.Select(n => (JsonObject)n!))
            {
                if (readsFirst.TryGetValue((string)node["id"]!, out SortedSet<string>? read) && read.Count > 0)
                {
                    node["attrs"]!["reads_before_write"] = string.Join(", ", read);
                }
            }

            return new JsonObject
            {
                ["execution_model"] = "group-chat-speaker",
                ["framework"] = "agent-framework",
                ["framework_version"] = version,
                ["id"] = info.Id,
                ["nodes"] = nodes,
                ["edges"] = edges,
                ["channels"] = channels,
                ["start_nodes"] = new JsonArray(Id((string)Reflect.Get(workflow, "StartExecutorId")!)),
                ["output_nodes"] = new JsonArray(bindings.Where(b => outputIds.Contains(b.Id)).Select(b => (JsonNode)Id(b.Id)).ToArray()),
                ["provenance"] = new JsonObject
                {
                    ["kind"] = "dotnet-assembly",
                    ["path"] = provenance,
                    ["extractor"] = "agent-framework-dotnet",
                },
            };
        }
    }

    /// The message types an executor accepts, sends and yields, as its built object records them.
    private sealed class NodeFacts
    {
        public SortedSet<string> Accepts { get; } = new(StringComparer.Ordinal);

        public SortedSet<string> Sends { get; } = new(StringComparer.Ordinal);

        public SortedSet<string> Yields { get; } = new(StringComparer.Ordinal);

        /// The executor declares its protocol, and the engine checks its sends and yields against it.
        public bool DeclaresProtocol { get; private set; }

        /// The handlers could not be read outside a run.
        public bool Unread { get; set; }

        public SortedSet<string> DeclaredSends { get; } = new(StringComparer.Ordinal);

        /// For each sent type, its base classes and interfaces.
        public Dictionary<string, SortedSet<string>> Supertypes { get; } = [];

        public void Read(object executor, bool isOutput)
        {
            this.Accepts.UnionWith(Types(Reflect.Get(executor, "InputTypes")));
            object? router = Reflect.Get(executor, "Router");
            if (Reflect.Get(router, "HasCatchAll") is true)
            {
                this.Accepts.Add("Any");
            }

            List<string> results = this.Sent(Reflect.Get(router, "DefaultOutputTypes"));
            if (Reflect.Get(Reflect.Get(executor, "Options"), "AutoSendMessageHandlerResultObject") is not false)
            {
                this.Sends.UnionWith(results);
            }

            object? protocol = Reflect.Call(executor, "DescribeProtocol");
            if (Reflect.Has(protocol, "Sends") && Reflect.Has(protocol, "Yields"))
            {
                this.DeclaresProtocol = true;
                this.Accepts.UnionWith(Types(Reflect.Get(protocol, "Accepts")));
                if (Reflect.Get(protocol, "AcceptsAll") is true)
                {
                    this.Accepts.Add("Any");
                }

                this.DeclaredSends.UnionWith(this.Sent(Reflect.Get(protocol, "Sends")));
                this.Sends.UnionWith(this.DeclaredSends);
                if (isOutput)
                {
                    this.Yields.UnionWith(Types(Reflect.Get(protocol, "Yields")));
                }

                return;
            }

            List<string> declared = this.Sent(Reflect.Call(executor, "ConfigureSentTypes"));
            if (!(declared.Count == 1 && declared[0] == "object"))
            {
                this.Sends.UnionWith(declared);
            }

            if (isOutput)
            {
                this.Yields.UnionWith(Types(Reflect.Call(executor, "ConfigureYieldTypes")));
            }
        }

        /// The spellings of the types in `set`; records their supertypes.
        private List<string> Sent(object? set)
        {
            List<Type> types = set is IEnumerable items ? items.OfType<Type>().ToList() : [];
            foreach (Type t in types)
            {
                if (TypeNames.Supertypes(t) is { Count: > 0 } supertypes)
                {
                    this.Supertypes[TypeNames.Spell(t)] = supertypes;
                }
            }

            return types.Select(TypeNames.Spell).ToList();
        }
    }

    private static JsonArray Sockets(IEnumerable<string> types, bool input) =>
        new(types.Select(t => (JsonNode)(input
            ? new JsonObject { ["name"] = t, ["type_repr"] = t, ["mandatory"] = true }
            : new JsonObject { ["name"] = t, ["type_repr"] = t, ["may_emit"] = true })).ToArray());

    /// Binds every request port of a sub-workflow to each step its host feeds that takes `ExternalRequest` (not `Any`).
    private static void BindRequestPorts(List<(JsonObject Node, Extracted Sub)> hosts, JsonArray nodes, JsonArray edges)
    {
        Dictionary<string, JsonObject> byId = nodes.Select(n => (JsonObject)n!).ToDictionary(n => (string)n["id"]!);
        foreach ((JsonObject host, Extracted sub) in hosts)
        {
            if (sub.RequestPorts.Count == 0)
            {
                continue;
            }

            string hostId = (string)host["id"]!;
            IEnumerable<string> answerers = edges
                .Where(e => (string)e!["from"]!["node"]! == hostId)
                .Select(e => (string)e!["to"]!["node"]!)
                .Where(t => byId.TryGetValue(t, out JsonObject? target)
                    && target["inputs"]!.AsArray().Any(i => (string)i!["type_repr"]! == "ExternalRequest"))
                .Distinct();
            JsonArray bindings = host["subflow_ref"]!["in_bindings"]!.AsArray();
            foreach (string answerer in answerers)
            {
                foreach (string port in sub.RequestPorts)
                {
                    bindings.Add(new JsonObject
                    {
                        ["outer"] = new JsonObject { ["node"] = answerer, ["socket"] = "ExternalResponse" },
                        ["inner"] = new JsonObject { ["node"] = port, ["socket"] = "" },
                    });
                }
            }
        }
    }

    /// The channels of the state accesses; `readsFirst`: per executor, the channels whose first access by it only reads.
    private static JsonArray Channels(List<(string Executor, StateAccess Access)> state, out Dictionary<string, SortedSet<string>> readsFirst)
    {
        static string Scope((string Executor, StateAccess Access) s) => s.Access.Scope ?? $"{s.Executor}/default";

        var wholeScope = new HashSet<string>(state.Where(s => s.Access.Key is null).Select(Scope));
        var channels = new SortedDictionary<string, (SortedSet<string> Readers, SortedSet<string> Writers)>(StringComparer.Ordinal);
        var seen = new HashSet<(string, string)>();
        readsFirst = [];
        foreach ((string Executor, StateAccess Access) s in state)
        {
            string scope = Scope(s);
            string name = wholeScope.Contains(scope) ? $"{scope}/*" : $"{scope}/{s.Access.Key}";
            if (seen.Add((s.Executor, name)) && s.Access.Reads && !s.Access.Writes)
            {
                if (!readsFirst.TryGetValue(s.Executor, out SortedSet<string>? first))
                {
                    readsFirst[s.Executor] = first = new SortedSet<string>(StringComparer.Ordinal);
                }

                first.Add(name);
            }

            if (!channels.TryGetValue(name, out var channel))
            {
                channels[name] = channel = (new SortedSet<string>(StringComparer.Ordinal), new SortedSet<string>(StringComparer.Ordinal));
            }

            if (s.Access.Reads)
            {
                channel.Readers.Add(s.Executor);
            }

            if (s.Access.Writes)
            {
                channel.Writers.Add(s.Executor);
            }
        }

        return new JsonArray(channels.Select(c => (JsonNode)new JsonObject
        {
            ["name"] = c.Key,
            ["type_repr"] = "Any",
            ["reducer"] = "last-value",
            ["writers"] = new JsonArray(c.Value.Writers.Select(w => (JsonNode)w).ToArray()),
            ["readers"] = new JsonArray(c.Value.Readers.Select(r => (JsonNode)r).ToArray()),
        }).ToArray());
    }

    /// Names agent executors (`<name>_<agent id>`, a new GUID per run without an id) after their agent, for a stable IR.
    private static Dictionary<string, string> StableIds(List<(string Id, object Binding)> bindings)
    {
        var taken = new HashSet<string>(bindings.Select(b => b.Id));
        var result = new Dictionary<string, string>();
        IEnumerable<IGrouping<string, string>> named = bindings
            .Select(b => (b.Id, Agent: Reflect.Get(b.Binding, "RawValue") ?? Reflect.Get(b.Binding, "RawExecutorishData")))
            .Select(b => (b.Id, Name: Reflect.Get(b.Agent, "Name") as string, AgentId: Reflect.Get(b.Agent, "Id") as string))
            .Where(b => b.Name is not null && (b.Id.StartsWith(b.Name + "_", StringComparison.Ordinal) || b.Id == b.AgentId))
            .GroupBy(b => b.Name!, b => b.Id);
        foreach (IGrouping<string, string> group in named)
        {
            if (group.Count() == 1 && !taken.Contains(group.Key))
            {
                result[group.Single()] = group.Key;
            }
        }

        // an unnamed agent becomes `<type>_<n>`
        int unnamed = 0;
        foreach ((string id, object binding) in bindings)
        {
            object? agent = Reflect.Get(binding, "RawValue") ?? Reflect.Get(binding, "RawExecutorishData");
            if (agent is not null && Reflect.IsA(agent.GetType(), "Microsoft.Agents.AI.AIAgent") && Reflect.Get(agent, "Name") is null
                && (id == Reflect.Get(agent, "Id") as string || id.StartsWith("_", StringComparison.Ordinal) || Guid.TryParse(id.Split('_')[^1], out _)))
            {
                string name = $"{agent.GetType().Name}_{++unnamed}";
                if (!taken.Contains(name))
                {
                    result[id] = name;
                }
            }
        }

        return result;
    }

    /// The bound executor, or the one its factory constructs (constructing runs no handler).
    private static object? Instance(object binding, string id)
    {
        if (Reflect.Get(binding, "ExecutorInstance") is object instance)
        {
            return instance;
        }

        // `FactoryAsync` of a binding, `ProviderAsync` of a registration (before release 1.0.0-preview.251104.1)
        object? factory = Reflect.Get(binding, "FactoryAsync") ?? Reflect.Get(binding, "ProviderAsync");
        return factory is Delegate create ? Reflect.Await(create.DynamicInvoke(id)) : null;
    }

    /// The edges, and in `barriers` the targets of fan-in edges, which wait for a message from every source.
    private static JsonArray Edges(object workflow, Func<string, string> id, out HashSet<string> barriers)
    {
        var edges = new SortedDictionary<string, JsonObject>(StringComparer.Ordinal);
        barriers = [];
        foreach (object group in (IEnumerable)Reflect.Call(workflow, "ReflectEdges")!)
        {
            foreach (object info in (IEnumerable)Reflect.Get(group, "Value")!)
            {
                string kind = Reflect.Get(info, "Kind")!.ToString()!;
                object connection = Reflect.Get(info, "Connection")!;
                bool conditional = kind == "Direct" && Reflect.Get(info, "HasCondition") is true;
                if (kind == "FanIn")
                {
                    barriers.UnionWith(Strings(Reflect.Get(connection, "SinkIds")).Select(id));
                }

                foreach (string from in Strings(Reflect.Get(connection, "SourceIds")).Select(id))
                {
                    foreach (string to in Strings(Reflect.Get(connection, "SinkIds")).Select(id))
                    {
                        var edge = new JsonObject
                        {
                            ["from"] = new JsonObject { ["node"] = from, ["socket"] = "" },
                            ["to"] = new JsonObject { ["node"] = to, ["socket"] = "" },
                            ["kind"] = conditional ? "conditional" : "control",
                        };
                        if (conditional)
                        {
                            edge["branch"] = "condition";
                        }

                        edges.TryAdd($"{from}\u0000{to}", edge);
                    }
                }
            }
        }

        return new JsonArray(edges.Values.Select(e => (JsonNode)e).ToArray());
    }

    /// The version of `package` the project resolved, from the `.deps.json` next to its assembly.
    private static string? PackageVersion(string assembly, string package)
    {
        string deps = Path.ChangeExtension(assembly, ".deps.json");
        if (!File.Exists(deps))
        {
            return null;
        }

        using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(deps));
        if (!doc.RootElement.TryGetProperty("libraries", out JsonElement libraries))
        {
            return null;
        }

        return libraries.EnumerateObject()
            .Select(l => l.Name)
            .FirstOrDefault(n => n.StartsWith(package + "/", StringComparison.OrdinalIgnoreCase))?[(package.Length + 1)..];
    }

    private static List<string> Types(object? set) =>
        set is IEnumerable types ? types.OfType<Type>().Select(TypeNames.Spell).ToList() : [];

    private static IEnumerable<string> Strings(object? set) => set is IEnumerable items ? items.OfType<string>() : [];
}
