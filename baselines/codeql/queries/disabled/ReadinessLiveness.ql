/**
 * @name Unreachable node (orphan / island)
 * @description A declared LangGraph node is unreachable from START by static edges and is never a routing target.
 * @kind problem
 * @problem.severity warning
 * @id apsis-baseline/readiness-liveness
 */

import python
import lib.LangGraphGraph

predicate isRoutingTarget(string n) { exists(Expr loc | lgRoutingTarget(loc, n)) }

/** Reachable from START; a routing target counts as reachable, as the static edges omit dynamic routing. */
predicate reachableFromStart(string n) {
  n = "__start__"
  or
  isRoutingTarget(n)
  or
  exists(string m | reachableFromStart(m) and lgEdge(_, m, n))
}

/** The reconstruction is anchored: some edge leaves START. */
predicate hasStartEdge() { lgEdge(_, "__start__", _) }

from MethodCall site, string n
where
  site.method() = "add_node" and
  n = site.getArg(0).(StringLiteral).getText() and
  hasStartEdge() and
  not reachableFromStart(n)
select site,
  "Node '" + n + "' is unreachable from START and is never a routing target (orphan/island; never runs)."
