"""Convert Python source to a JSON-compatible AST (comments included) and back.

>>> from pyast_json import source_to_json, json_to_source
>>> data = source_to_json("x = 1  # one\\n")
>>> data["body"][0]["comments"]
[' one']
>>> print(json_to_source(data), end="")
# one
x = 1
"""
import sys as _sys

if _sys.version_info < (3, 9):  # pragma: no cover
    raise ImportError("pyast_json requires Python 3.9 or later")

from ._util import dumps, loads
from .decode import encode_source, json_to_ast, json_to_source
from .encode import ast_to_json, read_comments, source_to_json
from .errors import ConversionError, PyAstJsonError, UnsupportedNodeError
from .schema import build_schema, is_valid, load_schema, validate

__version__ = "1.0.0"

__all__ = [
    "source_to_json", "ast_to_json", "read_comments",
    "json_to_source", "json_to_ast", "encode_source",
    "dumps", "loads", "load_schema", "build_schema", "validate", "is_valid",
    "PyAstJsonError", "UnsupportedNodeError", "ConversionError",
    "__version__",
]
