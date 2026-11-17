"""Access to the JSON schema and optional validation (needs ``jsonschema``)."""
from __future__ import annotations

import functools
import json
from importlib import resources

from ._util import deep_recursion
from .spec import build_schema

__all__ = ["build_schema", "load_schema", "validate", "is_valid"]


@functools.lru_cache(maxsize=None)
def _schema_text() -> str:
    return resources.files(__package__).joinpath("schema.json").read_text(encoding="utf-8")


def load_schema() -> dict:
    """The schema shipped with the package (a fresh copy on every call)."""
    return json.loads(_schema_text())


@functools.lru_cache(maxsize=None)
def _validator():
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise ImportError("validation needs the 'jsonschema' package: "
                          "pip install 'pyast-json[validate]'") from exc
    return jsonschema.Draft202012Validator(load_schema())


def validate(data) -> None:
    """Raise ``jsonschema.ValidationError`` if ``data`` does not match the schema."""
    with deep_recursion():
        _validator().validate(data)


def is_valid(data) -> bool:
    """True if ``data`` matches the schema."""
    with deep_recursion():
        return _validator().is_valid(data)
