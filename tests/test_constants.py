"""Literal values must survive JSON exactly, including the awkward ones."""
import ast
import json
import math

import pytest

import pyast_json
from pyast_json.decode import decode_constant
from pyast_json.encode import encode_constant

VALUES = [
    None, True, False, 0, 7, 10**400, "", "text", "üñí 𝄞", "\x00\n\t",
    "\ud800", "\udb7f\udc00",               # lone surrogates; JSON would merge the pair
    0.0, 1.5, 1e-310, 1e308, math.inf, 2j, complex(0, math.inf),
    b"", b"\x00\x7f\x80\xff", ...,
]


@pytest.mark.parametrize("value", VALUES, ids=repr)
def test_constant_survives_json(value):
    encoded = json.loads(json.dumps(encode_constant(value), allow_nan=False))
    decoded = decode_constant(encoded)
    assert type(decoded) is type(value)
    assert decoded == value or (decoded is value)


def test_float_is_tagged_and_int_is_not():
    assert encode_constant(1) == 1
    assert encode_constant(1.0) == {"_type": "float", "value": 1.0}
    assert encode_constant(math.inf) == {"_type": "float", "value": "inf"}
    assert encode_constant(b"ab") == {"_type": "bytes", "latin1": "ab"}
    assert encode_constant(...) == {"_type": "ellipsis"}
    assert encode_constant("\ud800") == {"_type": "str", "escaped": "\\ud800"}


def test_nan_constant():
    assert math.isnan(decode_constant({"_type": "float", "value": "nan"}))


def test_bare_integral_float_is_an_integer():
    assert decode_constant(3.0) == 3 and type(decode_constant(3.0)) is int


def test_bare_fractional_float_is_rejected():
    with pytest.raises(pyast_json.ConversionError):
        decode_constant(1.5)


def _module_of(*values):
    return {"_type": "Module", "body": [
        {"_type": "Expr", "value": {"_type": "Constant", "value": v, "kind": None}}
        for v in values]}


def _evaluate_each(source):
    return [eval(compile(ast.Expression(stmt.value), "<test>", "eval"))
            for stmt in ast.parse(source).body]


def test_values_without_literal_form_become_expressions():
    """The parser never produces these, but the schema allows them."""
    weird = [-5, {"_type": "float", "value": -0.0}, {"_type": "float", "value": "-inf"},
             {"_type": "float", "value": "nan"},
             {"_type": "complex", "real": -1.5, "imag": -2},
             {"_type": "complex", "real": 0, "imag": "nan"}]
    data = _module_of(*weird)
    if _has_jsonschema():
        pyast_json.validate(data)
    got = _evaluate_each(pyast_json.json_to_source(data))
    assert got[0] == -5
    assert got[1] == 0.0 and math.copysign(1, got[1]) == -1
    assert got[2] == -math.inf
    assert math.isnan(got[3])
    assert got[4] == complex(-1.5, -2)
    assert got[5].real == 0 and math.isnan(got[5].imag)


def test_negative_constant_keeps_precedence():
    data = {"_type": "Module", "body": [{"_type": "Expr", "value": {
        "_type": "BinOp", "op": {"_type": "Pow"},
        "left": {"_type": "Constant", "value": -2, "kind": None},
        "right": {"_type": "Constant", "value": 2, "kind": None}}}]}
    assert _evaluate_each(pyast_json.json_to_source(data)) == [4]


def test_u_prefix_kept():
    out = pyast_json.json_to_source(pyast_json.source_to_json("x = u'a'\n"))
    assert out == "x = u'a'\n"


def _has_jsonschema():
    try:
        import jsonschema  # noqa: F401
        return True
    except ImportError:
        return False
