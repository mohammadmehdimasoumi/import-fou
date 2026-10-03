"""Exception hierarchy for Fou.

Every error raised deliberately by Fou derives from :class:`FouError`, so callers
can catch the whole family with a single ``except FouError``.
"""

from __future__ import annotations


class FouError(Exception):
    """Base class for all errors raised on purpose by Fou."""


class LocationError(FouError):
    """The project location does not exist, is not a directory, or is not accessible."""


class InvalidOptionError(FouError, ValueError):
    """An argument passed to Fou has an invalid type or value."""


class InvalidDepthError(InvalidOptionError):
    """``depth`` is neither ``"all"`` nor a non-negative integer."""


class InvalidExtensionsError(InvalidOptionError):
    """``extensions`` is neither ``"all"`` nor a non-empty list of extensions."""


class InvalidExcludeError(InvalidOptionError):
    """``exclude`` contains something that is not a usable pattern."""


class InvalidInspectionTypeError(InvalidOptionError):
    """A requested inspection ``type`` is malformed or unsupported."""


class SaveError(FouError):
    """A result could not be saved."""


class InvalidSaveFormatError(SaveError, InvalidOptionError):
    """The requested save ``format`` is not supported."""


class InvalidSavePathError(SaveError, InvalidOptionError):
    """The requested save ``path`` is missing or unusable."""
