/**
 * @name A single instance is shared across multiple graph nodes
 * @description One variable is registered as more than one node (add_node) or component (add_component), so they alias one instance.
 * @kind problem
 * @problem.severity warning
 * @id apsis-baseline/shared-instance-aliasing
 */

import python
import lib.LangGraphGraph
import lib.HaystackGraph

/** A call registering `v` as a node/component instance: add_node(name, v) or add_component(name, v). */
predicate registersInstance(Call c, Variable v, string kind) {
  c.(MethodCall).method() = "add_node" and kind = "node" and c.getArg(1).(Name).getVariable() = v
  or
  c.getFunc().(Attribute).getName() = "add_component" and
  kind = "component" and
  c.getArg(1).(Name).getVariable() = v
}

from Call site, Variable v, string kind
where
  registersInstance(site, v, kind) and
  exists(Call other | registersInstance(other, v, kind) and other != site) and
  // report once: only at the textually-last registration of this instance
  not exists(Call later |
    registersInstance(later, v, kind) and
    later.getLocation().getStartLine() > site.getLocation().getStartLine()
  )
select site,
  "Instance '" + v.getId() + "' is registered as more than one " + kind +
    " (aliasing / shared mutable state)."
