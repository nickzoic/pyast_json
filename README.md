# pyast-json

[![tests](https://github.com/nickzoic/pyast_json/actions/workflows/tests.yml/badge.svg)](https://github.com/nickzoic/pyast_json/actions/workflows/tests.yml)


Convert Python source code into a JSON-compatible abstract syntax tree, and
back again. The JSON form is described by a JSON Schema (draft 2020-12),
shipped with the package.

- Every node is an object whose `"_type"` is the class name in Python's
  `ast` module: `{"_type": "Name", "id": "x", "ctx": {"_type": "Load"}}`.
- Comments are kept: each statement may carry a `"comments"` list, and the
  `Module` may carry trailing comments. Their text is preserved exactly,
  their position approximately.
- Literal values (docstrings included) are preserved exactly, including
  floats, `inf`, complex numbers, bytes, `...` and strings containing lone
  surrogates, all of which survive a trip through any JSON implementation.
- Covers the grammar of Python 3.9 to 3.15: `match`, `except*`, type
  parameters and `type` aliases, t-strings, lazy imports, and more.

## Install

```
pip install .                 # the library and the pyast-json command
pip install '.[validate]'     # plus jsonschema, for schema validation
pip install '.[test]'         # plus pytest, for running the tests
```

Requires Python 3.9 or later and has no required dependencies.

## Library

```python
import pyast_json

data = pyast_json.source_to_json(open("mod.py", "rb").read())  # dicts, lists, scalars
text = pyast_json.dumps(data, indent=1)                       # JSON text
source = pyast_json.json_to_source(data)                      # Python source

pyast_json.validate(data)        # raises jsonschema.ValidationError if invalid
schema = pyast_json.load_schema()
```

| Function | Purpose |
| --- | --- |
| `source_to_json(source, filename=...)` | `str` or `bytes` source to the JSON structure |
| `ast_to_json(tree, comments=None, trailing=())` | an `ast.Module` to the JSON structure |
| `json_to_source(data)` | the JSON structure to Python source, with comments |
| `json_to_ast(data)` | the JSON structure to an `ast.Module` (no comments) |
| `encode_source(source)` | bytes for writing, honouring a coding cookie |
| `read_comments(source)` | `(line, text)` for each comment |
| `dumps(data, indent=None)`, `loads(text)` | JSON text out and in, coping with very deep trees |
| `load_schema()`, `build_schema()` | the shipped schema / the schema rebuilt from the spec |
| `validate(data)`, `is_valid(data)` | schema validation (needs `jsonschema`) |

Errors derive from `pyast_json.PyAstJsonError` (a `ValueError`):
`UnsupportedNodeError` when encoding, `ConversionError` when decoding.
Invalid Python source raises `SyntaxError`.

## Command line

```
pyast-json encode mod.py -o mod.json [--indent N] [--validate]
pyast-json decode mod.json -o mod.py [--validate] [--check]
pyast-json schema -o schema.json
```

Use `-` for stdin. `python -m pyast_json` works too.

## Tests

```
pip install '.[test]'
pytest                              # quick suite, including fuzz tests
pytest --cov                        # with coverage (fails under 90%)
pytest --runslow                    # also round-trips the entire standard library
PYAST_FUZZ_EXAMPLES=2000 pytest -m fuzz   # a longer fuzz run
```

Continuous integration (`.github/workflows/tests.yml`) runs the suite with
coverage on Python 3.9 to 3.14 and on Linux, macOS and Windows, the
whole-standard-library test, and a longer fuzz run.

## Notes and limits

- `json_to_source` uses `ast.unparse`, so formatting is normalized:
  quotes, parentheses and line breaks may differ from the original.
- Comments are attached to the statement they are in or on, or else to the
  next statement. A comment after the last line of a block therefore moves
  to just before the following statement.
- The `u` prefix of string literals is kept, except inside f-strings, where
  `ast.unparse` drops it. The literal value is unchanged.
- Source positions and `# type:` comment fields are not stored (`# type:`
  comments are kept as ordinary comments).
- Trees using newer syntax convert back only on a Python that has it;
  otherwise `ConversionError` says which version is needed.
- The schema checks structure, not meaning: data that is structurally valid
  but impossible in Python (e.g. assigning to a literal) produces code that
  will not compile.

## Development

`src/pyast_json/spec.py` is the single source of truth for the node
classes and fields. After editing it, regenerate the shipped schema:

```
python -c "import json, pyast_json.spec as s; print(json.dumps(s.build_schema(), indent=2))" > src/pyast_json/schema.json
```

A test checks that the shipped schema and the spec agree.

## License

CC0 1.0 Universal (public domain dedication). See `LICENSE`.
