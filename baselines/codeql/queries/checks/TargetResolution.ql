/**
 * @name Routing or connection target names a nonexistent node
 * @description A static edge, a routing target or a pipeline connection names a node or component that is never declared.
 * @kind problem
 * @problem.severity error
 * @id apsis-baseline/target-resolution
 */

import python
import lib.LangGraphGraph
import lib.HaystackGraph

from Expr loc, string target, string why
where
  exists(MethodCall c | lgEdge(c, _, target) and loc = c) and
  not lgKnownName(target) and
  why = "edge target"
  or
  lgRoutingTarget(loc, target) and
  not lgKnownName(target) and
  why = "routing target"
  or
  // Haystack: only in files that register some component with add_component
  exists(ConnectCall c | hsEdge(c, _, target) and loc = c) and
  not hsComponent(target) and
  exists(string n | hsComponent(n)) and
  why = "connect target"
select loc, "Unresolved " + why + " '" + target + "': names no declared node/component."
