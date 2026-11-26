//! Assignability over the IR type grammar: `Any`, `Optional[T]`, `Union[A, B]`, `A | B`, `list[T]`.
//! Types compare by the spelling of their members; there is no subtype lattice.

fn split_top_level(s: &str) -> Vec<String> {
    let mut parts = Vec::new();
    let mut depth = 0i32;
    let mut cur = String::new();
    for c in s.chars() {
        match c {
            '[' => {
                depth += 1;
                cur.push(c);
            }
            ']' => {
                depth -= 1;
                cur.push(c);
            }
            ',' | '|' if depth == 0 => {
                parts.push(cur.trim().to_string());
                cur.clear();
            }
            _ => cur.push(c),
        }
    }
    if !cur.trim().is_empty() {
        parts.push(cur.trim().to_string());
    }
    parts
}

fn is_any(t: &str) -> bool {
    let t = t.trim();
    t.is_empty() || t == "Any"
}

/// A visual builder's spelling of any value (`string | number | json`); the top type under coercion.
fn is_generic_value_union(t: &str) -> bool {
    const PRIMITIVES: &[&str] = &["string", "number", "boolean", "json", "array", "object", "any"];
    let ms = members(t);
    ms.len() >= 2 && ms.iter().all(|m| PRIMITIVES.contains(&m.to_lowercase().as_str()))
}

fn without_whitespace(t: &str) -> String {
    t.split_whitespace().collect()
}

/// The members of `Optional[T]`, `Union[A, B]` or `A | B` without `None`; the type itself otherwise.
fn members(t: &str) -> Vec<String> {
    let n = without_whitespace(t);
    let body = n
        .strip_prefix("Optional[")
        .or_else(|| n.strip_prefix("Union["))
        .and_then(|s| s.strip_suffix(']'))
        .unwrap_or(&n);
    split_top_level(body).into_iter().filter(|m| m != "None" && m != "NoneType").collect()
}

/// The members of a container's element type (`list[T]`, `set[T]`, ...), else of the type itself.
fn elem_members(t: &str) -> Vec<String> {
    const CONTAINERS: &[&str] = &["list[", "set[", "tuple[", "sequence[", "iterable[", "frozenset["];
    let n = without_whitespace(t);
    let inner = CONTAINERS.iter().find_map(|c| n.strip_prefix(c)).and_then(|s| s.strip_suffix(']'));
    members(inner.unwrap_or(&n))
}

/// An `Optional[..]`, or a union with a `None` member.
pub(crate) fn nullable(t: &str) -> bool {
    let t = t.trim();
    t.starts_with("Optional[")
        || t.split(['|', ',']).any(|p| matches!(p.trim().trim_end_matches(']').trim(), "None" | "NoneType"))
}

/// `int`, possibly optional or wrapped in `Annotated[int, ...]`.
pub(crate) fn is_integer(t: &str) -> bool {
    let n = without_whitespace(t);
    let body = n
        .strip_prefix("Annotated[")
        .and_then(|s| s.strip_suffix(']'))
        .map(|s| split_top_level(s).into_iter().next().unwrap_or_default())
        .unwrap_or(n.clone());
    members(&body).iter().any(|m| m == "int")
}

/// Without coercion every member of `ot` must be in `it`; under coercion (visual builders) they share a member.
pub(crate) fn assignable(ot: &str, it: &str, coercive: bool) -> bool {
    if is_any(ot) || is_any(it) {
        return true;
    }
    if coercive {
        if is_generic_value_union(ot) || is_generic_value_union(it) {
            return true;
        }
        let o = elem_members(ot);
        let i = elem_members(it);
        o.iter().any(|m| i.contains(m)) || i.iter().any(|m| o.contains(m))
    } else {
        let it_members = members(it);
        members(ot).iter().all(|m| it_members.contains(m))
    }
}

/// `it` is a container whose element type accepts `ot`, as for a join that receives a list.
pub(crate) fn collectible(ot: &str, it: &str) -> bool {
    if is_any(ot) || is_any(it) {
        return true;
    }
    let elems = elem_members(it);
    if elems == members(it) {
        return false; // `it` is not a container
    }
    members(ot).iter().all(|m| elems.contains(m))
}
