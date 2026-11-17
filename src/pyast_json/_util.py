"""Small helpers shared by the encoder, decoder and command line."""
from __future__ import annotations

import contextlib
import json
import sys


@contextlib.contextmanager
def deep_recursion(limit: int = 10_000):
    """Long operator chains ("a" + "b" + ...) nest deeply; allow for them."""
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, limit))
    try:
        yield
    finally:
        sys.setrecursionlimit(old)


def dumps(data, indent: int | None = None) -> str:
    """Serialize a structure produced by source_to_json() as JSON text.

    Non-ASCII text is kept readable; deeply nested trees are handled.
    """
    with deep_recursion():
        text = json.dumps(data, indent=indent, ensure_ascii=False, allow_nan=False)
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:  # stray surrogates outside Constant values
            text = json.dumps(data, indent=indent, allow_nan=False)
    return text


def loads(text: str | bytes):
    """Parse JSON text produced by dumps() (deeply nested trees are handled)."""
    with deep_recursion():
        return json.loads(text)
