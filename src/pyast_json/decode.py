"""JSON-compatible structure -> Python source.

The structure is rebuilt as an ``ast`` tree and printed with ``ast.unparse``.
Comments are carried through unparsing as placeholder statements (a bare,
uniquely named identifier on its own line) that are then replaced by the
comment lines, at the indentation of the statement they belong to.
"""
from __future__ import annotations

import ast
import codecs
import math
import re
import sys
import uuid

from ._util import deep_recursion
from .errors import ConversionError
from .spec import ALLOWED_CLASSES, CLASS_FIELDS, COMMENTS, INT_TYPES, NODE_TYPES, STR_TYPES, TAG

__all__ = ["json_to_source", "json_to_ast", "decode_constant", "constant_expr",
           "source_encoding", "encode_source"]

_PY = sys.version.split()[0]


def _comment_texts(raw, where: str) -> list:
    """Validate a ``comments`` value: null, or a list of strings."""
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(t, str) for t in raw):
        raise ConversionError(f"{where}: comments must be a list of strings")
    return raw


def json_to_source(data: dict) -> str:
    """Return Python source code (ending in a newline) for a Module structure."""
    if not isinstance(data, dict) or data.get(TAG) != "Module":
        raise ConversionError("top-level object must be a Module")
    trailing = _comment_texts(data.get(COMMENTS), "Module")
    with deep_recursion():
        for _ in range(8):  # retry in the (astronomically unlikely) event of a marker clash
            builder = _Builder("_pyast_comment_" + uuid.uuid4().hex + "_")
            module = builder.node(data)
            ast.fix_missing_locations(module)
            code = ast.unparse(module)
            if code.count(builder.prefix) == len(builder.comments):
                break
        else:  # pragma: no cover
            raise RuntimeError("could not choose a unique comment marker")
    return _splice_comments(code, builder.prefix, builder.comments, trailing)


def json_to_ast(data: dict) -> ast.AST:
    """Rebuild the ``ast`` tree (comments are dropped).

    Values that have no literal form (negative numbers, NaN...) are returned
    as the expressions ``json_to_source`` would print for them.
    """
    with deep_recursion():
        tree = _Builder(None).node(data)
    return ast.fix_missing_locations(tree)


# --------------------------------------------------------------------------
# Values
# --------------------------------------------------------------------------

def _is_default(value) -> bool:
    return value is None or value == [] or value == 0


def _as_int(value) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        if not value.is_integer():
            raise ConversionError(f"expected an integer, got {value!r}")
        return int(value)
    if not isinstance(value, int):
        raise ConversionError(f"expected an integer, got {value!r}")
    return value


def _real(value) -> float:
    if isinstance(value, str):
        if value not in ("inf", "-inf", "nan"):
            raise ConversionError(f"bad float value {value!r}")
    elif not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConversionError(f"bad float value {value!r}")
    return float(value)


def decode_constant(value):
    """Python value of the JSON form of an ``ast.Constant`` value."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):          # a JSON number like 3.0 counts as an integer
        return _as_int(value)
    if isinstance(value, dict):
        tag = value.get(TAG)
        try:
            if tag == "float":
                return _real(value["value"])
            if tag == "complex":
                return complex(_real(value["real"]), _real(value["imag"]))
            if tag == "bytes":
                return value["latin1"].encode("latin-1")
            if tag == "ellipsis":
                return ...
            if tag == "str":
                return value["escaped"].encode("ascii").decode("unicode_escape")
        except (KeyError, AttributeError, UnicodeError) as exc:
            raise ConversionError(f"bad constant {value!r}") from exc
    raise ConversionError(f"bad constant {value!r}")


def _neg(node: ast.expr) -> ast.expr:
    return ast.UnaryOp(op=ast.USub(), operand=node)


def constant_expr(value, kind=None) -> ast.expr:
    """An expression whose value is ``value``.

    Usually a plain Constant.  Values that have no literal form in Python
    (negative numbers, NaN, complex numbers with a real part) - which the
    parser never produces but the schema allows - become the equivalent
    arithmetic expression so that ast.unparse emits valid code.
    """
    if isinstance(value, bool) or value is None or value is ... or isinstance(value, bytes):
        return ast.Constant(value=value, kind=None)
    if isinstance(value, str):
        return ast.Constant(value=value, kind=kind if kind == "u" else None)
    if isinstance(value, int):
        return ast.Constant(value=value, kind=None) if value >= 0 else _neg(ast.Constant(-value))
    if isinstance(value, float):
        if math.isnan(value):
            return ast.BinOp(left=ast.Constant(math.inf), op=ast.Sub(),
                             right=ast.Constant(math.inf))
        if math.copysign(1.0, value) < 0:
            return _neg(ast.Constant(-value))
        return ast.Constant(value=value, kind=None)
    if isinstance(value, complex):
        real, imag = value.real, value.imag
        subtract = False
        if math.isnan(imag):
            imag_node = ast.BinOp(left=ast.Constant(complex(0, math.inf)), op=ast.Sub(),
                                  right=ast.Constant(complex(0, math.inf)))
        else:
            subtract = math.copysign(1.0, imag) < 0
            imag_node = ast.Constant(complex(0.0, -imag if subtract else imag))
        if real == 0.0 and math.copysign(1.0, real) > 0:
            return _neg(imag_node) if subtract else imag_node
        return ast.BinOp(left=constant_expr(real), op=ast.Sub() if subtract else ast.Add(),
                         right=imag_node)
    raise ConversionError(f"bad constant {value!r}")


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------

class _Builder:
    def __init__(self, prefix: str | None):
        self.prefix = prefix              # None: drop comments
        self.comments: list[list[str]] = []

    def node(self, data, expected: str = "mod") -> ast.AST:
        if not isinstance(data, dict) or not isinstance(data.get(TAG), str):
            raise ConversionError(f"expected an AST node object, got {data!r:.80}")
        name = data[TAG]
        fields = CLASS_FIELDS.get(name)
        if fields is None:
            raise ConversionError(f"unknown node type {name!r}")
        if name not in ALLOWED_CLASSES[expected]:
            raise ConversionError(f"{name} is not allowed where {expected} is expected")
        cls = getattr(ast, name, None)
        if not (isinstance(cls, type) and issubclass(cls, ast.AST)):
            raise ConversionError(f"ast.{name} needs a newer Python than {_PY}")
        if name == "Constant":
            value = decode_constant(data.get("value"))
            if expected in ("fstring_part", "tstring_part") and not isinstance(value, str):
                raise ConversionError("the literal parts of an f/t-string must be strings")
            return constant_expr(value, data.get("kind"))

        kwargs = {}
        for f in fields:
            value = self.value(data.get(f.name, f.default()), f)
            if f.name in cls._fields:
                kwargs[f.name] = value
            elif not _is_default(value):
                raise ConversionError(f"{name}.{f.name} needs a newer Python than {_PY}")
        for extra in cls._fields:  # type_comment, type_ignores
            kwargs.setdefault(extra, [] if extra == "type_ignores" else None)
        if name == "ImportFrom" and kwargs.get("level") is None:
            kwargs["level"] = 0
        if name == "DictComp" and kwargs["value"] is None and sys.version_info < (3, 15):
            raise ConversionError(f"DictComp without a value ({{**x for x in y}}) "
                                  f"needs a newer Python than {_PY}")
        return cls(**kwargs)

    def value(self, raw, field):
        if not field.is_list:
            return self.item(raw, field)
        if not isinstance(raw, list):
            raise ConversionError(f"expected a list for {field.name!r}")
        if field.base != "stmt" or self.prefix is None:
            return [self.item(x, field) for x in raw]
        out = []
        for stmt in raw:
            if isinstance(stmt, dict):
                texts = _comment_texts(stmt.get(COMMENTS), stmt.get(TAG, "statement"))
                if texts:
                    out.append(self._marker(texts))
            out.append(self.item(stmt, field))
        return out

    def item(self, raw, field):
        if raw is None:
            if field.nullable or field.base == "singleton":
                return None
            raise ConversionError(f"{field.name!r} must not be null")
        base = field.base
        if base in NODE_TYPES:
            return self.node(raw, base)
        if base in INT_TYPES:
            return _as_int(raw)
        if base in STR_TYPES:
            if not isinstance(raw, str):
                raise ConversionError(f"expected a string for {field.name!r}")
            return raw
        if base == "singleton" and isinstance(raw, bool):
            return raw
        raise ConversionError(f"bad value {raw!r:.80} for {field.name!r}")

    def _marker(self, texts) -> ast.stmt:
        index = len(self.comments)
        self.comments.append(list(texts))
        return ast.Expr(value=ast.Name(id=f"{self.prefix}{index}", ctx=ast.Load()))


# --------------------------------------------------------------------------
# Comment splicing
# --------------------------------------------------------------------------

_LINE_BREAKS = re.compile(r"\r\n|\r|\n")


def _comment_lines(indent: str, texts) -> list[str]:
    lines = []
    for text in texts:  # the schema forbids line breaks; split defensively anyway
        lines.extend(indent + "#" + part for part in _LINE_BREAKS.split(text))
    return lines


def _splice_comments(code: str, prefix: str, comments, trailing) -> str:
    marker = re.compile(r"( *)" + re.escape(prefix) + r"(\d+)")
    out: list[str] = []
    held: list[str] = []   # comment lines waiting for their statement
    for line in code.split("\n"):
        m = marker.fullmatch(line)
        if m:
            held.extend(_comment_lines(m.group(1), comments[int(m.group(2))]))
        elif held and not line.strip():
            out.append(line)   # blank line before a def: put it above the comments
        else:
            out.extend(held)
            held.clear()
            out.append(line)
    out.extend(held)
    out.extend(_comment_lines("", trailing))
    text = "\n".join(out).lstrip("\n")
    return text + "\n" if text.strip() else ""


# --------------------------------------------------------------------------
# Writing source files
# --------------------------------------------------------------------------

_CODING = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")


def source_encoding(source: str) -> str:
    """The encoding named by a coding cookie in the first two lines, else ``utf-8``."""
    for line in source.split("\n", 2)[:2]:
        m = _CODING.match(line)
        if m:
            try:
                return codecs.lookup(m.group(1)).name
            except LookupError:
                break
        if line.strip() and not line.lstrip().startswith("#"):
            break
    return "utf-8"


def encode_source(source: str) -> bytes:
    """Encode generated source for writing to a file, honouring a coding cookie."""
    return source.encode(source_encoding(source))
