"""Types for the provider-shape contract.

Lives in its own module so concrete shape submodules can import from it
without circling back through `cold_read.providers.__init__`, which in
turn imports the submodules to build SHAPES.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class EnvField:
    """A single environment variable a shape needs to operate."""

    name: str
    description: str
    secret: bool = False


@dataclass(frozen=True)
class EvalResult:
    """Uniform return type for `ProviderShape.run()`."""

    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class CredentialTestResult:
    """Outcome of `credential_test()`. Always returned; never raised."""

    ok: bool
    reason: str | None = None


RunFn = Callable[[str, list[Path], dict], EvalResult]
CredentialTestFn = Callable[[dict], CredentialTestResult]


@dataclass(frozen=True)
class ProviderShape:
    """The contract every backend meets. One value per shape, registered
    under cold_read.providers.SHAPES by name."""

    name: str
    credential_fields: tuple[EnvField, ...]
    requires_deployment_map: bool
    run: RunFn
    credential_test: CredentialTestFn


class CredentialsMissingError(RuntimeError):
    """Raised by a shape when its required env fields are not set."""
