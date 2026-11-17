import ast
import collections
import json
import pathlib

import pytest

import pyast_json
from pyast_json._util import deep_recursion
from pyast_json.encode import normalize_source

DATA_DIR = pathlib.Path(__file__).parent / "data"


def pytest_addoption(parser):
    parser.addoption("--runslow", action="store_true", default=False,
                     help="also run slow tests (whole standard library round trip)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        return
    skip = pytest.mark.skip(reason="slow; use --runslow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def metaschema():
    return json.loads((DATA_DIR / "metaschema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def jsonschema():
    return pytest.importorskip("jsonschema")


def canonical_dump(tree) -> str:
    """ast.dump ignoring the u'' prefix flag (presentation only; see test_fuzz)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            node.kind = None
    with deep_recursion():
        return ast.dump(tree)


def _comment_texts(source):
    return collections.Counter(text for _, text in pyast_json.read_comments(source))


def check_roundtrip(source, validate=True):
    """source -> JSON text -> source; the result must parse to the same AST
    and contain the same comments.  Returns (data, regenerated source)."""
    data = pyast_json.source_to_json(source)
    data = pyast_json.loads(pyast_json.dumps(data))           # must survive real JSON
    if validate:
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            pass
        else:
            pyast_json.validate(data)
    regenerated = pyast_json.json_to_source(data)
    original = normalize_source(source)
    assert canonical_dump(ast.parse(regenerated)) == canonical_dump(ast.parse(original))
    assert _comment_texts(regenerated) == _comment_texts(original)
    return data, regenerated


@pytest.fixture
def roundtrip():
    return check_roundtrip
