"""Command line interface: ``pyast-json {encode,decode,schema}``."""
from __future__ import annotations

import argparse
import ast
import json
import sys

from . import __version__
from ._util import deep_recursion, dumps, loads
from .decode import encode_source, json_to_ast, json_to_source
from .encode import source_to_json
from .errors import PyAstJsonError
from .schema import load_schema, validate


def _read(path: str, binary: bool):
    if path == "-":
        return sys.stdin.buffer.read() if binary else sys.stdin.read()
    with open(path, "rb" if binary else "r", **({} if binary else {"encoding": "utf-8"})) as fh:
        return fh.read()


def _write(path: str | None, data: bytes) -> None:
    if path:
        with open(path, "wb") as fh:
            fh.write(data)
        return
    out = getattr(sys.stdout, "buffer", None)
    if out is None:  # e.g. a StringIO in tests
        sys.stdout.write(data.decode("utf-8", "surrogateescape"))
    else:
        sys.stdout.flush()
        out.write(data)
        out.flush()


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="pyast-json",
        description="Convert Python source to a JSON AST (with comments) and back.")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    enc = sub.add_parser("encode", help="Python source -> JSON")
    enc.add_argument("input", help="Python file, or - for stdin")
    enc.add_argument("-o", "--output", help="output file (default: stdout)")
    enc.add_argument("--indent", type=int, default=1,
                     help="JSON indentation; 0 for compact output (default: 1)")
    enc.add_argument("--validate", action="store_true",
                     help="validate the result against the schema (needs jsonschema)")

    dec = sub.add_parser("decode", help="JSON -> Python source")
    dec.add_argument("input", help="JSON file, or - for stdin")
    dec.add_argument("-o", "--output", help="output file (default: stdout)")
    dec.add_argument("--validate", action="store_true",
                     help="validate the input against the schema first (needs jsonschema)")
    dec.add_argument("--check", action="store_true",
                     help="verify that the generated code parses back to the same tree")

    sch = sub.add_parser("schema", help="print the JSON schema")
    sch.add_argument("-o", "--output", help="output file (default: stdout)")
    return ap


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "encode":
            name = "<stdin>" if args.input == "-" else args.input
            data = source_to_json(_read(args.input, binary=True), name)
            if args.validate:
                validate(data)
            text = dumps(data, indent=args.indent if args.indent > 0 else None)
            _write(args.output, (text + "\n").encode("utf-8"))

        elif args.command == "decode":
            data = loads(_read(args.input, binary=False))
            if args.validate:
                validate(data)
            source = json_to_source(data)
            if args.check:
                with deep_recursion():
                    same = ast.dump(ast.parse(source)) == ast.dump(json_to_ast(data))
                if not same:
                    raise PyAstJsonError("generated code does not parse back to the same tree")
            _write(args.output, encode_source(source))

        else:
            _write(args.output, (json.dumps(load_schema(), indent=2) + "\n").encode("utf-8"))
    except (PyAstJsonError, SyntaxError, OSError, UnicodeError, ValueError) as exc:
        print(f"pyast-json: error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # jsonschema.ValidationError etc.
        if type(exc).__name__ == "ValidationError":
            print(f"pyast-json: invalid: {exc.message}", file=sys.stderr)
            return 1
        raise
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
