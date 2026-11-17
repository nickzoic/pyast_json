"""The AST classes and fields covered by the JSON representation.

The tables mirror CPython's ``Parser/Python.asdl`` (union of the grammars of
Python 3.9 to 3.15) and are the single source of truth for the schema, the
encoder and the decoder.  Field notation is ``"<type> <name>"`` where
``<type>`` is ``base`` (one value), ``base?`` (value or null), ``base*``
(list) or ``base?*`` (list whose items may be null).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SCHEMA_ID = "urn:pyast-json:schema:1"
TAG = "_type"            # discriminator key on every node
COMMENTS = "comments"    # optional comment list on statements / Module

# --------------------------------------------------------------------------
# Field notation: "<type> <name>", where <type> is
#   base        a single value
#   base?       a single value or null
#   base*       a list
#   base?*      a list whose items may be null
# --------------------------------------------------------------------------

CATEGORIES: dict[str, dict[str, str]] = {
    "mod": {
        "Module": "stmt* body",
    },
    "stmt": {
        "FunctionDef": "identifier name, arguments args, stmt* body, expr* decorator_list, "
                       "expr? returns, type_param* type_params",
        "AsyncFunctionDef": "identifier name, arguments args, stmt* body, expr* decorator_list, "
                            "expr? returns, type_param* type_params",
        "ClassDef": "identifier name, expr* bases, keyword* keywords, stmt* body, "
                    "expr* decorator_list, type_param* type_params",
        "Return": "expr? value",
        "Delete": "expr* targets",
        "Assign": "expr* targets, expr value",
        "TypeAlias": "expr name, type_param* type_params, expr value",
        "AugAssign": "expr target, operator op, expr value",
        "AnnAssign": "expr target, expr annotation, expr? value, flag simple",
        "For": "expr target, expr iter, stmt* body, stmt* orelse",
        "AsyncFor": "expr target, expr iter, stmt* body, stmt* orelse",
        "While": "expr test, stmt* body, stmt* orelse",
        "If": "expr test, stmt* body, stmt* orelse",
        "With": "withitem* items, stmt* body",
        "AsyncWith": "withitem* items, stmt* body",
        "Match": "expr subject, match_case* cases",
        "Raise": "expr? exc, expr? cause",
        "Try": "stmt* body, excepthandler* handlers, stmt* orelse, stmt* finalbody",
        "TryStar": "stmt* body, excepthandler* handlers, stmt* orelse, stmt* finalbody",
        "Assert": "expr test, expr? msg",
        "Import": "alias* names, flag? is_lazy",
        "ImportFrom": "identifier? module, alias* names, count? level, flag? is_lazy",
        "Global": "identifier* names",
        "Nonlocal": "identifier* names",
        "Expr": "expr value",
        "Pass": "",
        "Break": "",
        "Continue": "",
    },
    "expr": {
        "BoolOp": "boolop op, expr* values",
        "NamedExpr": "expr target, expr value",
        "BinOp": "expr left, operator op, expr right",
        "UnaryOp": "unaryop op, expr operand",
        "Lambda": "arguments args, expr body",
        "IfExp": "expr test, expr body, expr orelse",
        "Dict": "expr?* keys, expr* values",
        "Set": "expr* elts",
        "ListComp": "expr elt, comprehension* generators",
        "SetComp": "expr elt, comprehension* generators",
        "DictComp": "expr key, expr? value, comprehension* generators",
        "GeneratorExp": "expr elt, comprehension* generators",
        "Await": "expr value",
        "Yield": "expr? value",
        "YieldFrom": "expr value",
        "Compare": "expr left, cmpop* ops, expr* comparators",
        "Call": "expr func, expr* args, keyword* keywords",
        "FormattedValue": "expr value, conversion conversion, JoinedStr? format_spec",
        "Interpolation": "expr value, string str, conversion conversion, JoinedStr? format_spec",
        "JoinedStr": "fstring_part* values",
        "TemplateStr": "tstring_part* values",
        "Constant": "constant value, constant_kind? kind",
        "Attribute": "expr value, identifier attr, expr_context ctx",
        "Subscript": "expr value, expr slice, expr_context ctx",
        "Starred": "expr value, expr_context ctx",
        "Name": "identifier id, expr_context ctx",
        "List": "expr* elts, expr_context ctx",
        "Tuple": "expr* elts, expr_context ctx",
        "Slice": "expr? lower, expr? upper, expr? step",
    },
    "expr_context": {"Load": "", "Store": "", "Del": ""},
    "boolop": {"And": "", "Or": ""},
    "operator": {name: "" for name in (
        "Add", "Sub", "Mult", "MatMult", "Div", "Mod", "Pow", "LShift",
        "RShift", "BitOr", "BitXor", "BitAnd", "FloorDiv")},
    "unaryop": {"Invert": "", "Not": "", "UAdd": "", "USub": ""},
    "cmpop": {name: "" for name in (
        "Eq", "NotEq", "Lt", "LtE", "Gt", "GtE", "Is", "IsNot", "In", "NotIn")},
    "excepthandler": {
        "ExceptHandler": "expr? type, identifier? name, stmt* body",
    },
    "pattern": {
        "MatchValue": "expr value",
        "MatchSingleton": "singleton value",
        "MatchSequence": "pattern* patterns",
        "MatchMapping": "expr* keys, pattern* patterns, identifier? rest",
        "MatchClass": "expr cls, pattern* patterns, identifier* kwd_attrs, pattern* kwd_patterns",
        "MatchStar": "identifier? name",
        "MatchAs": "pattern? pattern, identifier? name",
        "MatchOr": "pattern* patterns",
    },
    "type_param": {
        "TypeVar": "identifier name, expr? bound, expr? default_value",
        "ParamSpec": "identifier name, expr? default_value",
        "TypeVarTuple": "identifier name, expr? default_value",
    },
}

# ASDL "product" types: a single class whose name is also the type name.
PRODUCTS: dict[str, str] = {
    "comprehension": "expr target, expr iter, expr* ifs, flag is_async",
    "arguments": "arg* posonlyargs, arg* args, arg? vararg, arg* kwonlyargs, "
                 "expr?* kw_defaults, arg? kwarg, expr* defaults",
    "arg": "identifier arg, expr? annotation",
    "keyword": "identifier? arg, expr value",
    "alias": "identifier name, identifier? asname",
    "withitem": "expr context_expr, expr? optional_vars",
    "match_case": "pattern pattern, expr? guard, stmt* body",
}

# Narrower unions used where the parser only ever produces certain classes
# (and where ast.unparse relies on it): f-string / t-string parts.
REFINED_UNIONS: dict[str, dict[str, str]] = {
    "fstring_part": {"Constant": "Constant_str", "FormattedValue": "FormattedValue"},
    "tstring_part": {"Constant": "Constant_str", "Interpolation": "Interpolation"},
}

# Fields of ast classes that are deliberately not represented.
IGNORED_FIELDS = frozenset({"type_comment", "type_ignores"})

# Builtin (non-node) field types.
INT_TYPES = frozenset({"flag", "count", "conversion"})
STR_TYPES = frozenset({"identifier", "string", "constant_kind"})

_REF = "#/$defs/"


@dataclass(frozen=True)
class Field:
    name: str
    base: str
    is_list: bool
    nullable: bool          # the value itself (scalar) or each item (list)

    def default(self):
        """Value used when a field is absent (older Python, or omitted JSON)."""
        if self.is_list:
            return []
        return 0 if self.base == "flag" else None


def _parse_fields(text: str) -> tuple[Field, ...]:
    fields = []
    for part in filter(None, (p.strip() for p in text.split(","))):
        typ, name = part.split()
        m = re.fullmatch(r"(\w+)(\?)?(\*)?", typ)
        if not m:
            raise ValueError(f"bad field spec {part!r}")
        fields.append(Field(name, m.group(1), bool(m.group(3)), bool(m.group(2))))
    return tuple(fields)


CLASS_FIELDS: dict[str, tuple[Field, ...]] = {}
CLASS_CATEGORY: dict[str, str] = {}
for _cat, _classes in CATEGORIES.items():
    for _cls, _text in _classes.items():
        CLASS_FIELDS[_cls] = _parse_fields(_text)
        CLASS_CATEGORY[_cls] = _cat
for _cls, _text in PRODUCTS.items():
    CLASS_FIELDS[_cls] = _parse_fields(_text)
    CLASS_CATEGORY[_cls] = _cls

STATEMENT_CLASSES = frozenset(CATEGORIES["stmt"])
# Every field base type whose values are AST node objects.
NODE_TYPES = frozenset(CATEGORIES) | frozenset(CLASS_FIELDS) | frozenset(REFINED_UNIONS)
# For every node field type: the classes a value of that type may have.
ALLOWED_CLASSES: dict[str, frozenset] = {
    **{name: frozenset({name}) for name in CLASS_FIELDS},
    **{cat: frozenset(classes) for cat, classes in CATEGORIES.items()},
    **{name: frozenset(members) for name, members in REFINED_UNIONS.items()},
}


# --------------------------------------------------------------------------
# Schema generation
# --------------------------------------------------------------------------

def _ref(name: str) -> dict:
    return {"$ref": _REF + name}


def _tagged_union(members: dict[str, str], description: str) -> dict:
    """Union discriminated by "_type".

    Written as  allOf[ (_type == T) -> T-schema, ... ]  using anyOf/not, which
    is the "if/then" idiom expressible in the supported subset.  Unlike a
    plain anyOf over the members, a validator never descends into the
    children of a non-matching member, so validation cost stays linear in
    the size of the tree instead of exponential in its depth.
    """
    return {
        "description": description,
        "type": "object",
        "required": [TAG],
        "properties": {TAG: {"enum": list(members)}},
        "allOf": [
            {"anyOf": [{"not": {"properties": {TAG: {"const": tag}}}}, _ref(target)]}
            for tag, target in members.items()
        ],
    }


def _field_schema(field: Field) -> dict:
    item = _ref(field.base)
    if field.nullable:
        item = {"anyOf": [item, {"type": "null"}]}
    if field.is_list:
        return {"type": "array", "items": item}
    return item


def _class_schema(name: str, fields: tuple[Field, ...], description: str) -> dict:
    props = {TAG: {"const": name}}
    for f in fields:
        props[f.name] = _field_schema(f)
    if name in STATEMENT_CLASSES or name == "Module":
        props[COMMENTS] = _ref("comments")
    return {
        "description": description,
        "type": "object",
        "properties": props,
        "required": [TAG] + [f.name for f in fields],
        "additionalProperties": False,
    }


def _signature(name: str, fields: tuple[Field, ...]) -> str:
    def typ(f):
        return f.base + ("?" if f.nullable else "") + ("*" if f.is_list else "")
    return f"ast.{name}(" + ", ".join(f"{typ(f)} {f.name}" for f in fields) + ")"


def _builtin_defs() -> dict:
    real = {
        "description": "A float: a JSON number, or one of the non-finite values as a string.",
        "anyOf": [{"type": "number"}, {"enum": ["inf", "-inf", "nan"]}],
    }

    def tagged(tag, props, description):
        return {
            "description": description,
            "type": "object",
            "properties": {TAG: {"const": tag}, **props},
            "required": [TAG, *props],
            "additionalProperties": False,
        }

    return {
        "identifier": {"description": "Identifier or dotted module name.",
                       "type": "string", "minLength": 1},
        "string": {"type": "string"},
        "count": {"type": "integer", "minimum": 0},
        "flag": {"description": "Boolean stored as an int, as in the ast module.",
                 "enum": [0, 1]},
        "conversion": {"description": "-1 (none), or ord('a'), ord('r'), ord('s').",
                       "enum": [-1, 97, 114, 115]},
        "singleton": {"enum": [None, True, False]},
        "constant_kind": {"description": "'u' for u'...' string literals.", "enum": ["u"]},
        "comments": {
            "description": "Comment texts without the leading '#', one per line.",
            "type": "array",
            "items": {"type": "string", "pattern": "^[^\\r\\n\\u0000]*$"},
        },
        "real": real,
        "constant_float": tagged("float", {"value": _ref("real")}, "A float constant."),
        "constant_complex": tagged("complex", {"real": _ref("real"), "imag": _ref("real")},
                                   "A complex constant (the parser only produces imaginary literals)."),
        "constant_bytes": tagged("bytes", {"latin1": {"type": "string",
                                                      "pattern": "^[\\u0000-\\u00ff]*$"}},
                                 "A bytes constant; character U+00XX stands for byte 0xXX."),
        "constant_ellipsis": tagged("ellipsis", {}, "The Ellipsis constant (...)."),
        "constant_str_escaped": tagged(
            "str", {"escaped": {"type": "string", "pattern": "^[ -~]*$"}},
            "A string containing lone surrogates (which JSON strings cannot hold faithfully), "
            "in Python's 'unicode_escape' encoding."),
        "constant": {
            "description": "Value of an ast.Constant.",
            "anyOf": [
                {"type": ["null", "boolean", "integer", "string"]},
                _ref("constant_float"), _ref("constant_complex"),
                _ref("constant_bytes"), _ref("constant_ellipsis"), _ref("constant_str_escaped"),
            ],
        },
        "Constant_str": {
            "description": "A Constant whose value is a string (literal part of an f/t-string).",
            "allOf": [_ref("Constant"), {"properties": {"value": {
                "anyOf": [{"type": "string"}, _ref("constant_str_escaped")]}}}],
        },
    }


def build_schema() -> dict:
    defs: dict[str, dict] = {}
    for cat, classes in CATEGORIES.items():
        defs[cat] = _tagged_union({c: c for c in classes}, f"ast.{cat}: any of its subclasses.")
        for cls in classes:
            defs[cls] = _class_schema(cls, CLASS_FIELDS[cls], _signature(cls, CLASS_FIELDS[cls]))
    for cls in PRODUCTS:
        defs[cls] = _class_schema(cls, CLASS_FIELDS[cls], _signature(cls, CLASS_FIELDS[cls]))
    for name, members in REFINED_UNIONS.items():
        defs[name] = _tagged_union(members, f"Parts of an {'f' if name[0] == 'f' else 't'}-string.")
    defs.update(_builtin_defs())
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": "Python 3 abstract syntax tree (with comments) as JSON",
        "description": (
            "A Python module as produced by pyast_json.source_to_json(): every node is an object whose '_type' is "
            "the name of its class in Python's ast module (grammar of Python 3.9 to 3.15). "
            "Statements may carry 'comments'. Positions and type comments are not stored."
        ),
        "$ref": _REF + "Module",
        "$defs": defs,
    }
