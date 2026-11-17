"""Source -> JSON -> source must reproduce the same AST and the same comments."""
import ast
import importlib.util
import pathlib
import sys
import sysconfig
import textwrap

import pytest

# (minimum Python version, source)
SNIPPETS = {
    "empty": ((3, 9), ""),
    "comments_only": ((3, 9), "# just a comment\n#another\n"),
    "simple_statements": ((3, 9), """
        import os, sys as system
        from . import sibling
        from ..pkg.mod import (a, b as c)
        from mod import *
        x = y = 1
        x += 2; x -= 3
        del x
        assert y, "message"
        global g
        pass
        """),
    "functions": ((3, 9), """
        @decorator
        @decorator.with_args(1, key=2)
        def f(a, b=1, /, c=2, *args, d, e=3, **kwargs) -> "ret":
            '''Docstring.'''
            def inner():
                nonlocal a
                a = 1
            return lambda x, *y, z=1, **w: (x, y, z, w)

        async def g():
            async with a as b, c:
                await d()
            async for i in e():
                yield i
            yield from ()  if False else None
        """),
    "classes": ((3, 9), """
        class A(B, C, metaclass=M, **extra):
            '''Class docstring.'''
            x: int = 1
            y: "str"
            (z): int

            @property
            def p(self):
                return super().p
        """),
    "control_flow": ((3, 9), """
        if a:
            pass
        elif b:
            pass
        else:
            if c:
                pass
            d()
        while x:
            break
        else:
            continue
        for i, (j, k) in enumerate(z):
            pass
        else:
            pass
        try:
            pass
        except ValueError as e:
            raise TypeError() from e
        except (KeyError, IndexError):
            raise
        except:
            pass
        else:
            pass
        finally:
            pass
        with open(f) as fh, other():
            pass
        """),
    "expressions": ((3, 9), """
        x = (a if b else c, not a, -a, +a, ~a, a and b or c, a < b <= c != d is not e in f not in g)
        y = a @ b // c % d ** -e << f >> g & h | i ^ j
        z = [a, *b], {a, *b}, {**a, "k": v}, (a,), (), [], {}
        w = [i for i in a if i if not i], {i for i in a}, {k: v for k, v in a}, (i for i in a)
        s = a[1], a[1:2], a[::3], a[1:2, ::3, ...], a[b, c]
        v = (n := 10), f(*args, **kwargs, key=value), a.b.c
        lam = lambda: (yield)
        """),
    "literals": ((3, 9), r"""
        values = [
            None, True, False, ..., 0, 1, 0x_ff, 0o17, 0b101, 10**100, 123456789012345678901234567890,
            1.5, 1e-300, 1e999, .5, 1_000.000_1, 3j, 1e999j, 2.5j,
            'single', "double", '''triple''', r'raw\d', u'unicode prefix', 'üñíçødé ✓ 𝄞',
            b'bytes \x00\xff', rb'raw\bytes', 'escapes \n\t\x00\\', 'lone surrogate \ud800 \udc00',
            '\udb7f\udc00', 'emoji pair \U0001f600',
        ]
        """),
    "fstrings": ((3, 9), r"""
        a = f"{x}"
        b = f"pre {x!r:>{width}.{prec}} post {y!s} {z!a:x}"
        c = f'{x=}' f"{'nested'}" "plain" f"{{literal braces}}"
        d = f'''multi
        line {x}'''
        """),
    "fstrings_312": ((3, 12), """
        a = f"{"same quotes"}"
        b = f"{x:{"nested" + f"{y}"}}"
        c = f"{'\\n'.join(lines)}"
        """),
    "walrus_and_posonly": ((3, 9), """
        if (n := len(a)) > 10:
            print(f"{n=}")
        def f(a, /, b): ...
        """),
    "parenthesized_with": ((3, 10), """
        with (
            open(a) as fa,
            open(b) as fb,
        ):
            pass
        """),
    "match": ((3, 10), """
        match command.split():
            case [action]:
                pass
            case [action, obj, *rest] if obj:
                pass
            case Point(x=0, y=-1) | Point(1, 2) as p:
                pass
            case {"key": value, **others}:
                pass
            case {1: _, "b": [1, 2]}:
                pass
            case None | True | False:
                pass
            case -1 | 1.5 | -2+3j | "s" | b"b" | Color.RED:
                pass
            case (a, b, *_):
                pass
            case _:
                pass
        """),
    "except_star": ((3, 11), """
        try:
            pass
        except* (ValueError, TypeError) as eg:
            pass
        except* OSError:
            pass
        """),
    "type_params": ((3, 12), """
        type Alias = int
        type Generic[T, *Ts, **P] = Callable[P, tuple[T, *Ts]]
        class Box[T: (int, str), U: object]:
            def get[V](self, v: V) -> T: ...
        def f[T](x: T) -> T: ...
        """),
    "type_param_defaults": ((3, 13), """
        class A[T = int, *Ts = *tuple[int], **P = [int]]: ...
        type X[T: int = bool] = list[T]
        """),
    "tstrings": ((3, 14), """
        a = t"hello {name!r:>{width}}"
        b = t"{x=}" t'plain'
        """),
    "lazy_imports": ((3, 15), """
        lazy import json
        lazy from os import path
        """),
    "comprehension_unpacking": ((3, 15), """
        a = [*x for x in y]
        b = {**d for d in ds}
        """),
    "docstrings_everywhere": ((3, 9), '''
        """Module docstring with "quotes" and 'apostrophes' and \\\\backslashes\\\\."""

        def f():
            """Function docstring.

            Multi-line, with an escaped newline \\n and a tab\\t.
            """

        class C:
            """"Starts with a quote."""
        '''),
    "deep_nesting": ((3, 9), "x = " + " + ".join(f"'s{i}'" for i in range(2000)) + "\n"),
}

COMMENTED = """
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
\"\"\"Docstring.\"\"\"  # after docstring
import os  # trailing on import

# Section header
@decorator  # on decorator
# between decorator and def
def f(
    a,  # parameter a
    b,
):  # after the signature
    # first line of the body
    x = [1,  # inside a list
         2]
    if x:  # if header
        pass
    else:  # else header
        # in else
        pass
    # end of function body

class C:  # class header
    pass
    #   indented, oddly spaced comment   
# trailing 1
#trailing 2 # with hash
"""


@pytest.mark.parametrize("name", list(SNIPPETS))
def test_snippet(name, roundtrip):
    min_version, source = SNIPPETS[name]
    if sys.version_info < min_version:
        pytest.skip(f"needs Python {'.'.join(map(str, min_version))}")
    # jsonschema validates recursively; a 2000-level tree exceeds its stack
    roundtrip(textwrap.dedent(source), validate=(name != "deep_nesting"))


def test_commented_module(roundtrip):
    roundtrip(COMMENTED.lstrip("\n"))


def test_bytes_input_with_coding_cookie(roundtrip):
    source = "# -*- coding: latin-1 -*-\ns = 'caf\xe9'  # caf\xe9\n".encode("latin-1")
    data, regenerated = roundtrip(source)
    assert data["body"][0]["value"]["value"] == "caf\xe9"
    assert regenerated.splitlines()[0] == "# -*- coding: latin-1 -*-"


def test_crlf_and_bom(roundtrip):
    roundtrip(b"\xef\xbb\xbfx = 1\r\n# c\r\ny = '''a\r\nb'''\r\n")


STDLIB_SAMPLE = ["json", "typing", "dataclasses", "argparse", "asyncio.tasks", "enum",
                 "inspect", "textwrap", "tokenize", "ast", "string", "fractions",
                 "functools", "collections", "email.message", "difflib", "pprint"]


def _module_file(name):
    spec = importlib.util.find_spec(name)
    origin = getattr(spec, "origin", None)
    if not origin or not origin.endswith(".py"):
        pytest.skip(f"{name} has no Python source")
    return pathlib.Path(origin)


@pytest.mark.parametrize("module", STDLIB_SAMPLE)
def test_stdlib_sample(module, roundtrip):
    roundtrip(_module_file(module).read_bytes(), validate=False)


@pytest.mark.slow
def test_whole_stdlib(roundtrip):
    failures = []
    root = pathlib.Path(sysconfig.get_paths()["stdlib"])
    for path in sorted(root.rglob("*.py")):
        raw = path.read_bytes()
        try:
            ast.parse(raw)
        except (SyntaxError, ValueError):
            continue  # deliberately broken test files etc.
        try:
            roundtrip(raw, validate=False)
        except Exception as exc:  # collect them all
            failures.append(f"{path}: {type(exc).__name__}: {exc}"[:300])
    assert not failures, "\n".join(failures)
