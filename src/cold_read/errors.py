"""Bucket-labeled exceptions and the CLI formatter.

Every user-facing failure in this package raises one of three typed
errors that name which of the three artifact buckets the missing thing
lives in. The CLI catches them at the top level and prints a prefix
plus a suggestion, so users see the bucket label before the reason and
know which fix to try.

- `PackageResourceError` → bucket 1 (ships with the package): suggests
  reinstalling the tool.
- `UserConfigError` → bucket 2 (user-owned persistent): suggests
  running `resume-cold-read init` or editing `config.toml` directly.
- `InvocationError` → bucket 3 (per-invocation CLI args): the classic
  "your command line is wrong" error; exits 2 per Typer convention.
"""

from __future__ import annotations

from dataclasses import dataclass


class ColdReadError(Exception):
    """Base for every bucket-labeled user-facing error."""

    bucket: str = "package"
    exit_code: int = 1
    label: str = "error"

    def __init__(self, message: str, suggestion: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion


class PackageResourceError(ColdReadError):
    """A bucket-1 resource (packaged prompt, calibration image, manifest)
    is missing or unreadable. Fix path: reinstall the package."""

    bucket = "package"
    exit_code = 1
    label = "package"


class UserConfigError(ColdReadError):
    """A bucket-2 artifact is missing or invalid: no config dir, unset
    default_model, missing credentials, etc. Fix path: run init."""

    bucket = "config"
    exit_code = 1
    label = "config"


class InvocationError(ColdReadError):
    """A bucket-3 issue: CLI argument, flag, or file path provided by
    the user on this invocation. Fix path: rerun with corrected args."""

    bucket = "invocation"
    exit_code = 2
    label = "invocation"


@dataclass(frozen=True)
class ErrorLine:
    """Two strings a renderer emits: the prefixed message and the
    optional suggestion. Returned from `format_error` so the CLI's
    console wrapper can print with its own styling."""

    label: str
    message: str
    suggestion: str | None


def format_error(exc: ColdReadError) -> ErrorLine:
    return ErrorLine(label=exc.label, message=exc.message, suggestion=exc.suggestion)


__all__ = [
    "ColdReadError",
    "PackageResourceError",
    "UserConfigError",
    "InvocationError",
    "ErrorLine",
    "format_error",
]
