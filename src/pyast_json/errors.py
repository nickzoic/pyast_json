"""Exceptions raised by pyast_json."""


class PyAstJsonError(ValueError):
    """Base class for all pyast_json errors."""


class UnsupportedNodeError(PyAstJsonError):
    """The ast tree contains something the JSON representation cannot hold."""


class ConversionError(PyAstJsonError):
    """The JSON data is not a valid tree, or needs a newer Python than this one."""
