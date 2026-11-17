import ast
import doctest
import sys

import pytest

import pyast_json
from pyast_json import ConversionError, PyAstJsonError, UnsupportedNodeError


def test_package_doctest():
    assert doctest.testmod(pyast_json, raise_on_error=False).failed == 0


def test_error_hierarchy():
    assert issubclass(ConversionError, PyAstJsonError)
    assert issubclass(UnsupportedNodeError, PyAstJsonError)
    assert issubclass(PyAstJsonError, ValueError)


def test_syntax_error_propagates():
    with pytest.raises(SyntaxError):
        pyast_json.source_to_json("def (:\n")


@pytest.mark.parametrize("data", [
    None, [], {"_type": "Expr"}, {"body": []},
])
def test_top_level_must_be_module(data):
    with pytest.raises(ConversionError):
        pyast_json.json_to_source(data)


@pytest.mark.parametrize("stmt", [
    {"_type": "NoSuchNode"},
    {"_type": "Return", "value": {"_type": "Load"}},           # expr_context where expr expected
    {"_type": "Expr", "value": {"_type": "JoinedStr", "values": [
        {"_type": "Name", "id": "x", "ctx": {"_type": "Load"}}]}},  # not an f-string part
    {"_type": "Expr", "value": None},                          # required field is null
    {"_type": "Global", "names": "x"},                         # list expected
    {"_type": "Expr", "value": {"_type": "Name", "id": 3, "ctx": {"_type": "Load"}}},
    {"_type": "Expr", "value": {"_type": "Constant", "value": {"_type": "float"}}},
])
def test_invalid_nodes_raise_conversion_error(stmt):
    with pytest.raises((ConversionError, TypeError)):
        pyast_json.json_to_source({"_type": "Module", "body": [stmt]})


def test_unsupported_constant_in_ast():
    tree = ast.Module(body=[ast.Expr(ast.Constant(value=(1, 2)))], type_ignores=[])
    with pytest.raises(UnsupportedNodeError):
        pyast_json.ast_to_json(tree)


def test_ast_to_json_requires_module():
    with pytest.raises(UnsupportedNodeError):
        pyast_json.ast_to_json(ast.parse("x", mode="eval"))


@pytest.mark.skipif(sys.version_info >= (3, 15), reason="supported on 3.15+")
def test_lazy_import_needs_315():
    data = {"_type": "Module", "body": [{"_type": "Import", "is_lazy": 1, "names": [
        {"_type": "alias", "name": "json", "asname": None}]}]}
    with pytest.raises(ConversionError, match="newer Python"):
        pyast_json.json_to_source(data)


@pytest.mark.skipif(sys.version_info >= (3, 15), reason="supported on 3.15+")
def test_dict_comprehension_unpacking_needs_315():
    gen = {"_type": "comprehension", "target": {"_type": "Name", "id": "d", "ctx": {"_type": "Store"}},
           "iter": {"_type": "Name", "id": "ds", "ctx": {"_type": "Load"}}, "ifs": [], "is_async": 0}
    expr = {"_type": "DictComp", "key": {"_type": "Name", "id": "d", "ctx": {"_type": "Load"}},
            "value": None, "generators": [gen]}
    with pytest.raises(ConversionError, match="newer Python"):
        pyast_json.json_to_source({"_type": "Module", "body": [{"_type": "Expr", "value": expr}]})


def test_missing_optional_fields_get_defaults():
    """Hand-written data may omit fields; lists default to [] and optionals to None."""
    data = {"_type": "Module", "body": [
        {"_type": "FunctionDef", "name": "f",
         "args": {"_type": "arguments"},
         "body": [{"_type": "Pass"}]},
        {"_type": "ImportFrom", "module": "os", "names": [{"_type": "alias", "name": "path"}]},
    ]}
    assert pyast_json.json_to_source(data) == "def f():\n    pass\nfrom os import path\n"


# --------------------------------------------------------------------------
# Shapes that the schema allows but that cannot be printed faithfully.
# Found by the fuzz tests: ast.unparse pairs lists with zip(), which silently
# drops items, and raises for some combinations.
# --------------------------------------------------------------------------

def _name(id_):
    return {"_type": "Name", "id": id_, "ctx": {"_type": "Load"}}


def _const(value):
    return {"_type": "Constant", "value": value, "kind": None}


def _expr_module(expr):
    return {"_type": "Module", "body": [{"_type": "Expr", "value": expr}]}


BAD_SHAPES = {
    "dict keys shorter than values": {"_type": "Dict", "keys": [_const("a")],
                                      "values": [_const(1), _const(2)]},
    "dict keys longer than values": {"_type": "Dict", "keys": [_const("a"), _const("b")],
                                     "values": [_const(1)]},
    "compare without comparators": {"_type": "Compare", "left": _name("a"), "ops": [],
                                    "comparators": []},
    "compare ops/comparators mismatch": {"_type": "Compare", "left": _name("a"),
                                         "ops": [{"_type": "Lt"}, {"_type": "Lt"}],
                                         "comparators": [_name("b")]},
    "kw_defaults shorter than kwonlyargs": {"_type": "Lambda", "body": _name("x"), "args": {
        "_type": "arguments", "posonlyargs": [], "args": [], "vararg": None,
        "kwonlyargs": [{"_type": "arg", "arg": "k", "annotation": None}],
        "kw_defaults": [], "kwarg": None, "defaults": []}},
    "more defaults than parameters": {"_type": "Lambda", "body": _name("x"), "args": {
        "_type": "arguments", "posonlyargs": [], "args": [], "vararg": None,
        "kwonlyargs": [], "kw_defaults": [], "kwarg": None, "defaults": [_const(1)]}},
    "raise cause without exc": {"_type": "Raise", "exc": None, "cause": _name("e")},
}


@pytest.mark.parametrize("node", list(BAD_SHAPES.values()), ids=list(BAD_SHAPES))
def test_inconsistent_shapes_are_rejected(node):
    stmt = node if node["_type"] == "Raise" else {"_type": "Expr", "value": node}
    with pytest.raises(ConversionError):
        pyast_json.json_to_source({"_type": "Module", "body": [stmt]})


def test_matching_shapes_are_accepted():
    data = _expr_module({"_type": "Dict", "keys": [_const("a"), None],
                         "values": [_const(1), _name("m")]})
    assert pyast_json.json_to_source(data) == "{'a': 1, **m}\n"


def test_comments_must_be_strings():
    for bad in (True, [None], "text", [1]):
        data = {"_type": "Module", "body": [{"_type": "Pass", "comments": bad}]}
        with pytest.raises(ConversionError):
            pyast_json.json_to_source(data)
    with pytest.raises(ConversionError):
        pyast_json.json_to_source({"_type": "Module", "body": [], "comments": [None]})
