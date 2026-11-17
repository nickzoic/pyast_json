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
