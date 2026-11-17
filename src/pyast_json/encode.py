"""Python source -> JSON-compatible structure.

The result is made of dicts, lists, str, int, float, bool and None only, and
validates against the package's schema.  Comments are collected with the
tokenize module and attached to the statement they belong to:

* a comment inside a simple statement, or on the header lines of a compound
  statement (``def f():  # note``), belongs to that statement;
* any other comment belongs to the next statement in the file;
* comments after the last statement go into the Module's ``comments``.
"""
from __future__ import annotations

import ast
import bisect
import importlib.util
import io
import itertools
import math
import re
import tokenize

from ._util import deep_recursion
from .errors import UnsupportedNodeError
from .spec import CLASS_FIELDS, COMMENTS, IGNORED_FIELDS, INT_TYPES, NODE_TYPES, STR_TYPES, TAG

__all__ = ["source_to_json", "ast_to_json", "normalize_source", "read_comments",
           "attach_comments", "encode_constant"]

_MISSING = object()
_SURROGATE = re.compile("[\ud800-\udfff]")


def source_to_json(source: str | bytes, filename: str = "<unknown>") -> dict:
    """Parse Python source and return its JSON-compatible representation.

    ``source`` may be ``str`` or ``bytes``; bytes are decoded the way Python
    decodes source files (coding cookie, BOM, default UTF-8).
    Raises ``SyntaxError`` for invalid source.
    """
    source = normalize_source(source)
    tree = ast.parse(source, filename)
    attached, trailing = attach_comments(tree, read_comments(source))
    return ast_to_json(tree, attached, trailing)


def ast_to_json(tree: ast.Module, comments: dict | None = None, trailing=()) -> dict:
    """Convert an ``ast.Module``.

    ``comments`` maps ``id(stmt)`` to a list of comment texts to put before
    that statement; ``trailing`` are comment texts for the end of the module.
    """
    if not isinstance(tree, ast.Module):
        raise UnsupportedNodeError(f"expected an ast.Module, got {type(tree).__name__}")
    with deep_recursion():
        data = _Encoder(comments or {}).node(tree)
    if trailing:
        data[COMMENTS] = list(trailing)
    return data


def normalize_source(source: str | bytes) -> str:
    """Decode bytes like the interpreter does, and normalize newlines to ``\\n``."""
    if isinstance(source, (bytes, bytearray)):
        return importlib.util.decode_source(bytes(source))
    if source.startswith("\ufeff"):
        source = source[1:]
    return source.replace("\r\n", "\n").replace("\r", "\n")


def read_comments(source: str) -> list[tuple[int, str]]:
    """``(line number, text without '#')`` for every comment in the source."""
    return [(tok.start[0], tok.string[1:])
            for tok in tokenize.generate_tokens(io.StringIO(source).readline)
            if tok.type == tokenize.COMMENT]


# --------------------------------------------------------------------------
# Comment attachment
# --------------------------------------------------------------------------

def _start(stmt: ast.stmt) -> int:
    lines = [stmt.lineno]
    lines.extend(d.lineno for d in getattr(stmt, "decorator_list", ()))
    return min(lines)


def _child_statements(node: ast.AST) -> list[ast.stmt]:
    out = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.stmt):
            out.append(child)
        elif isinstance(child, (ast.excepthandler, getattr(ast, "match_case", ()))):
            out.extend(_child_statements(child))
    return out


def _header_end(stmt: ast.stmt) -> int:
    """Last line of a compound statement's header (decorators, signature, test...)."""
    end = stmt.lineno
    for child in ast.iter_child_nodes(stmt):
        if isinstance(child, (ast.stmt, ast.excepthandler, getattr(ast, "match_case", ()))):
            continue
        for n in ast.walk(child):
            e = getattr(n, "end_lineno", None)
            if e is not None and e > end:
                end = e
    return end


def attach_comments(tree: ast.Module, comments) -> tuple[dict[int, list[str]], list[str]]:
    """Assign ``(line, text)`` comments to statements.

    Returns ``({id(stmt): [text, ...]}, [trailing text, ...])``.
    """
    levels: dict[int, tuple[list[int], list[ast.stmt]]] = {}
    entries: list[tuple[int, int, ast.stmt]] = []
    order = itertools.count()

    stack = [(tree, tree.body)]
    while stack:  # pre-order, so that outer statements sort before inner ones
        owner, stmts = stack.pop()
        stmts = sorted(stmts, key=_start)
        levels[id(owner)] = ([_start(s) for s in stmts], stmts)
        for s in reversed(stmts):
            stack.append((s, _child_statements(s)))
        if owner is not tree:
            entries.append((_start(owner), next(order), owner))
    entries.sort(key=lambda e: (e[0], e[1]))
    entry_starts = [e[0] for e in entries]

    attached: dict[int, list[str]] = {}
    trailing: list[str] = []
    for line, text in comments:
        # innermost statement whose lines contain the comment
        node, owner = None, tree
        while True:
            starts, stmts = levels[id(owner)]
            i = bisect.bisect_right(starts, line) - 1
            if i < 0 or stmts[i].end_lineno < line:
                break
            node = owner = stmts[i]
        if node is not None and (not levels[id(node)][1] or line <= _header_end(node)):
            target = node
        else:
            j = bisect.bisect_right(entry_starts, line)
            target = entries[j][2] if j < len(entries) else None
        if target is None:
            trailing.append(text)
        else:
            attached.setdefault(id(target), []).append(text)
    return attached, trailing


# --------------------------------------------------------------------------
# Node encoding
# --------------------------------------------------------------------------

def _real(x: float):
    if math.isfinite(x):
        return x
    return "nan" if math.isnan(x) else ("inf" if x > 0 else "-inf")


def encode_constant(value):
    """JSON form of the value of an ``ast.Constant``."""
    if isinstance(value, str):
        if _SURROGATE.search(value):  # JSON would merge/mangle these
            return {TAG: "str", "escaped": value.encode("unicode_escape").decode("ascii")}
        return value
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return {TAG: "float", "value": _real(value)}
    if isinstance(value, complex):
        return {TAG: "complex", "real": _real(value.real), "imag": _real(value.imag)}
    if isinstance(value, bytes):
        return {TAG: "bytes", "latin1": value.decode("latin-1")}
    if value is Ellipsis:
        return {TAG: "ellipsis"}
    raise UnsupportedNodeError(f"unsupported constant {value!r}")


class _Encoder:
    def __init__(self, comments: dict):
        self.comments = comments

    def node(self, node):
        name = type(node).__name__
        fields = CLASS_FIELDS.get(name)
        if fields is None or not isinstance(node, ast.AST):
            raise UnsupportedNodeError(f"unsupported node type {name}")
        out = {TAG: name}
        for f in fields:
            value = getattr(node, f.name, _MISSING)
            out[f.name] = f.default() if value is _MISSING else self.value(value, f)
        for extra in node._fields:  # fields of a newer Python we don't know about
            if (extra not in out and extra not in IGNORED_FIELDS
                    and getattr(node, extra, None) not in (None, [], 0)):
                raise UnsupportedNodeError(f"{name}.{extra} is not supported")
        texts = self.comments.get(id(node))
        if texts and isinstance(node, ast.stmt):
            out[COMMENTS] = list(texts)
        return out

    def value(self, value, field):
        if field.is_list:
            return [self.item(v, field) for v in value]
        return self.item(value, field)

    def item(self, value, field):
        base = field.base
        if value is None:
            return None
        if base in NODE_TYPES:
            return self.node(value)
        if base == "constant":
            return encode_constant(value)
        if base in INT_TYPES:
            return int(value)
        if base in STR_TYPES:
            return str(value)
        return value  # singleton: None / True / False
