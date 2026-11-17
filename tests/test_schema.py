"""The schema: shipped copy, metaschema conformance, coverage of the ast module."""
import ast

import pytest

import pyast_json
from pyast_json.spec import CATEGORIES, CLASS_FIELDS, IGNORED_FIELDS

# Classes in the ast module that are deliberately not represented.
NOT_REPRESENTED = {
    # deprecated aliases (never produced by the parser)
    "Num", "Str", "Bytes", "NameConstant", "Ellipsis", "Index", "ExtSlice", "Suite",
    "AugLoad", "AugStore", "Param", "slice",
    # other parse modes / type comments
    "Interactive", "Expression", "FunctionType", "TypeIgnore", "type_ignore",
}


def _all_ast_classes():
    seen, stack = set(), [ast.AST]
    while stack:
        cls = stack.pop()
        for sub in cls.__subclasses__():
            if sub not in seen and sub.__module__ in ("ast", "_ast"):
                seen.add(sub)
                stack.append(sub)
    return seen


def test_shipped_schema_matches_spec():
    assert pyast_json.load_schema() == pyast_json.build_schema()


def test_metaschema_validates_itself(metaschema, jsonschema):
    jsonschema.Draft202012Validator(metaschema).validate(metaschema)


def test_schema_is_in_the_supported_subset(metaschema, jsonschema):
    validator = jsonschema.Draft202012Validator(metaschema)
    validator.validate(pyast_json.load_schema())


def test_schema_is_valid_draft_2020_12(jsonschema):
    jsonschema.Draft202012Validator.check_schema(pyast_json.load_schema())


def test_all_local_refs_resolve():
    schema = pyast_json.load_schema()
    refs = []

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                refs.append(node["$ref"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    for ref in refs:
        assert ref.startswith("#/$defs/") and ref[len("#/$defs/"):] in schema["$defs"], ref


def test_every_concrete_ast_class_is_covered():
    missing = sorted(
        cls.__name__ for cls in _all_ast_classes()
        if cls.__name__ not in CATEGORIES and cls.__name__ not in NOT_REPRESENTED
        and cls.__name__ not in CLASS_FIELDS)
    assert not missing, f"ast classes without a schema: {missing}"


@pytest.mark.parametrize("name", sorted(CLASS_FIELDS))
def test_fields_match_running_python(name):
    cls = getattr(ast, name, None)
    if cls is None:
        pytest.skip(f"ast.{name} does not exist in this Python")
    ours = {f.name for f in CLASS_FIELDS[name]}
    theirs = set(cls._fields) - IGNORED_FIELDS
    assert theirs <= ours, f"fields not represented: {theirs - ours}"


def test_schema_rejects_bad_data(jsonschema):
    good = pyast_json.source_to_json("x = 1\n")
    assert pyast_json.is_valid(good)
    bad_examples = [
        {"_type": "Module"},                                         # missing body
        {"_type": "Module", "body": [{"_type": "Name", "id": "x"}]},  # expr where stmt expected
        {"_type": "Module", "body": [], "extra": 1},                 # unknown key
        {"_type": "Module", "body": [{"_type": "Expr", "value": {
            "_type": "Constant", "value": 1.5, "kind": None}}]},      # bare non-integer float
        {"_type": "Module", "body": [{"_type": "Pass", "comments": ["a\nb"]}]},  # newline
    ]
    for bad in bad_examples:
        assert not pyast_json.is_valid(bad), bad


def test_validation_is_not_exponential(jsonschema):
    """Deeply nested statements must validate quickly (tagged-union encoding)."""
    source = ""
    for depth in range(25):
        source += "    " * depth + "if x:\n"
    source += "    " * 25 + "pass\n"
    pyast_json.validate(pyast_json.source_to_json(source))
