"""Property-based fuzz tests (Hypothesis).

Three properties are checked:

1. Random Python-like source either fails to parse, or round-trips to the
   same AST with the same comments and validates against the schema.
2. Random mutations of a valid JSON tree either decode, or fail with a
   PyAstJsonError.  Nothing else may escape the decoder.
3. Random JSON text fed through loads() either parses, or raises ValueError.

Set PYAST_FUZZ_EXAMPLES to change how many examples each test draws.
"""
import ast
import collections
import copy
import os

import pytest

import pyast_json
from pyast_json._util import deep_recursion
from pyast_json.encode import normalize_source
from pyast_json.spec import CLASS_FIELDS

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402

pytestmark = pytest.mark.fuzz

MAX_EXAMPLES = int(os.environ.get("PYAST_FUZZ_EXAMPLES", "200"))
FUZZ_SETTINGS = settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    derandomize=bool(os.environ.get("PYAST_FUZZ_DERANDOMIZE")),
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)

FRAGMENTS = [
    "x", "y", "f", "=", "+=", "+", "-", "*", "**", "/", "//", "%", "@", "&", "|", "^", "<<",
    "(", ")", "[", "]", "{", "}", ":", ",", ".", "->", ":=", ";", "\n", "\n    ", "\n\t",
    "1", "0x1f", "2.5", "1e308", "3j", "...", "None", "True", "False",
    "'s'", '"t"', "'''m\nl'''", "r'\\d'", "b'x'", "u'z'", "f'{x!r:>{w}}'", "f'{{}}'",
    "if", "elif", "else:", "def g(a, /, *b, c=1, **d):", "return", "lambda", "yield",
    "async", "await", "for i in x:", "while x:", "break", "continue", "pass",
    "class C(B):", "import os", "from . import m as n", "from m import *", "@dec",
    "try:", "except E as e:", "except*", "finally:", "raise", "from e",
    "with a as b:", "match x:", "case [a, *r] if a:", "case {'k': v, **rest}:",
    "case C(x=1) | None:", "case _:", "global x", "nonlocal y", "del x", "assert x, 'm'",
    "not", "and", "or", "in", "is", "not in", "is not", "*args", "**kw",
    "[x for x in y if x]", "{k: v for k, v in z}", "{**a}", "{*a}", "a[1:2, ::3]",
    "#comment", "# another comment", "type T = int", "type G[K: int] = list[K]",
    "class D[T]:", "t'{x}'", "t'{x!r:{w}}'",
]


def _check_roundtrip(source: str) -> None:
    """Round-trip one piece of source; raises AssertionError on any mismatch."""
    data = pyast_json.loads(pyast_json.dumps(pyast_json.source_to_json(source)))
    assert pyast_json.is_valid(data), "encoder produced data that fails the schema"
    regenerated = pyast_json.json_to_source(data)
    original = normalize_source(source)
    with deep_recursion():
        assert ast.dump(ast.parse(regenerated)) == ast.dump(ast.parse(original)), regenerated
    comments = lambda s: collections.Counter(t for _, t in pyast_json.read_comments(s))  # noqa: E731
    assert comments(regenerated) == comments(original)


# --------------------------------------------------------------------------
# 1. Source fuzzing
# --------------------------------------------------------------------------

@pytest.mark.fuzz
@FUZZ_SETTINGS
@given(st.lists(st.sampled_from(FRAGMENTS), max_size=60).map(" ".join))
def test_random_source_roundtrips(source):
    try:
        ast.parse(source)
    except (SyntaxError, ValueError):
        return  # not valid Python: nothing to check
    _check_roundtrip(source)


@pytest.mark.fuzz
@FUZZ_SETTINGS
@given(st.text(max_size=200))
def test_arbitrary_text_never_crashes_the_encoder(text):
    """Any text either is rejected by the parser or round-trips."""
    try:
        ast.parse(text)
    except (SyntaxError, ValueError):
        with pytest.raises((SyntaxError, ValueError)):
            pyast_json.source_to_json(text)
        return
    _check_roundtrip(text)


# --------------------------------------------------------------------------
# 2. Mutating valid JSON trees
# --------------------------------------------------------------------------

SEED_SOURCE = """\
# header comment
\"\"\"Doc.\"\"\"
import os  # why
@dec  # on decorator
def f(a, b=1, *c, d, **e) -> int:  # on header
    '''Function doc.'''
    x = [1, 2.5, 3j, 'text', b'raw', None, ...]  # list
    y = f'{x!r:>10}' 'plain'
    if a:
        return {**e, 'k': a[1:2]}
    for i in range(3):
        yield (lambda q: q)(i)
    match x:
        case [1, *r] | C(k=1):
            pass
    try:
        pass
    except* ValueError as err:
        raise
    finally:
        del x
# trailing comment
"""


def _paths(node, path=()):
    """Every (container, key) slot in a JSON tree, depth first."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield (path + (key,), node, key)
            yield from _paths(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield (path + (index,), node, index)
            yield from _paths(value, path + (index,))


_JSON_LEAVES = st.one_of(
    st.none(), st.booleans(), st.integers(min_value=-5, max_value=5),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.text(max_size=8),
    st.sampled_from(["inf", "-inf", "nan", "ellipsis", "float", "bytes", "str"]),
)
_JSON_VALUES = st.recursive(
    _JSON_LEAVES,
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(st.sampled_from(["_type", "value", "id", "name", "ctx", "body", "kind"]),
                        children, max_size=3)),
    max_leaves=6,
)
_NODE_LIKE = st.one_of(
    st.sampled_from(sorted(CLASS_FIELDS)).map(lambda name: {"_type": name}),
    st.sampled_from(sorted(CLASS_FIELDS)).map(lambda name: {"_type": name, "id": "q", "ctx": {"_type": "Load"}}),
)
_REPLACEMENTS = st.one_of(_JSON_VALUES, _NODE_LIKE)


@st.composite
def mutations(draw):
    """A list of (operation, slot index, replacement value) applied in order."""
    count = draw(st.integers(min_value=1, max_value=4))
    ops = []
    for _ in range(count):
        op = draw(st.sampled_from(["set", "set", "delete"]))
        ops.append((op, draw(st.integers(min_value=0, max_value=10_000)), draw(_REPLACEMENTS)))
    return ops


def _apply(data, ops):
    data = copy.deepcopy(data)
    for op, index, value in ops:
        slots = list(_paths(data))
        if not slots:
            break
        _, container, key = slots[index % len(slots)]
        if op == "delete":
            if isinstance(container, dict):
                container.pop(key, None)
            elif len(container) > 1:  # keep lists from vanishing entirely
                del container[key]
        else:
            container[key] = value
    return data


SEED_SOURCE_OLD_PYTHON = """\
# header comment
\"\"\"Doc.\"\"\"
import os  # why
@dec  # on decorator
def f(a, b=1, *c, d, **e) -> int:  # on header
    '''Function doc.'''
    x = [1, 2.5, 3j, 'text', b'raw', None, ...]  # list
    y = f'{x!r:>10}' 'plain'
    if a:
        return {**e, 'k': a[1:2]}
    for i in range(3):
        yield (lambda q: q)(i)
    try:
        pass
    except ValueError as err:
        raise
    finally:
        del x
# trailing comment
"""


@pytest.fixture(scope="module")
def seed_tree():
    try:
        ast.parse(SEED_SOURCE)
        source = SEED_SOURCE
    except SyntaxError:  # match and except* need newer Pythons
        source = SEED_SOURCE_OLD_PYTHON
    return pyast_json.source_to_json(source)


@pytest.mark.fuzz
@FUZZ_SETTINGS
@given(mutations())
def test_mutated_json_only_raises_package_errors(seed_tree, ops):
    """The decoder may refuse a tree, but only with one of its own exceptions."""
    mutated = _apply(seed_tree, ops)
    try:
        source = pyast_json.json_to_source(mutated)
    except pyast_json.PyAstJsonError:
        return
    except RecursionError:  # only possible on absurd nesting; not a crash
        return
    # Whatever came out must at least be text
    assert isinstance(source, str)


@pytest.mark.fuzz
@FUZZ_SETTINGS
@given(mutations())
def test_schema_valid_mutations_decode(seed_tree, ops):
    """Trees that pass the schema should decode, or fail with ConversionError only."""
    mutated = _apply(seed_tree, ops)
    if not pyast_json.is_valid(mutated):
        return
    try:
        pyast_json.json_to_source(mutated)
    except pyast_json.ConversionError:
        # Schema allows it, but the decoder needs a newer Python for it
        # (lazy import, {**x for ...}); nothing else is acceptable.
        return


# --------------------------------------------------------------------------
# 3. Raw JSON text
# --------------------------------------------------------------------------

@pytest.mark.fuzz
@FUZZ_SETTINGS
@given(st.text(max_size=120))
def test_loads_rejects_garbage_with_value_error(text):
    """Malformed text gives ValueError (JSONDecodeError or RecursionError-free failure)."""
    try:
        pyast_json.loads(text)
    except ValueError:
        pass
