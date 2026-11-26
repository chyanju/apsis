#!/usr/bin/env python3
"""Remove the text that could describe the bug (docstrings, comments) from a benchmark source before it enters a prompt.

CLI: python3 clean_source.py <file>   prints the cleaned text of one file.
"""
import ast, json, sys

JSON_LEAK_KEYS = {"description", "note", "notes", "comment", "comments", "docstring", "info", "hint"}


def clean_python(src: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = node.body
            if (b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant)
                    and isinstance(b[0].value.value, str)):
                node.body = b[1:] or [ast.Pass()]
    return ast.unparse(tree)


def clean_json(src: str) -> str:
    def scrub(o):
        if isinstance(o, dict):
            return {k: ("" if k.lower() in JSON_LEAK_KEYS else scrub(v)) for k, v in o.items()}
        if isinstance(o, list):
            return [scrub(x) for x in o]
        return o
    return json.dumps(scrub(json.loads(src)), indent=2)


def clean_csharp(src: str) -> str:
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("/*", i):
            end = src.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        verbatim = src.startswith('@"', i) or src.startswith('$@"', i) or src.startswith('@$"', i)
        if verbatim or c == '"' or (c == "$" and src.startswith('$"', i)) or c == "'":
            quote = "'" if c == "'" else '"'
            j = src.index(quote, i) + 1
            while j < n:
                if verbatim and src.startswith('""', j):
                    j += 2
                elif not verbatim and src[j] == "\\":
                    j += 2
                elif src[j] == quote:
                    j += 1
                    break
                else:
                    j += 1
            out.append(src[i:j])
            i = j
            continue
        out.append(c)
        i += 1
    lines = [line.rstrip() for line in "".join(out).splitlines()]
    kept, blank = [], False
    for line in lines:
        if not line:
            if not blank and kept:
                kept.append("")
            blank = True
        else:
            kept.append(line)
            blank = False
    return "\n".join(kept).strip() + "\n"


def clean_file(path: str) -> str:
    src = open(path, encoding="utf-8").read()
    if path.endswith(".json"):
        return clean_json(src)
    if path.endswith(".cs"):
        return clean_csharp(src)
    return clean_python(src)


if __name__ == "__main__":
    print(clean_file(sys.argv[1]))
