"""Provider shapes: the post-`client_type`-string dispatch surface.

Each backend registers a single `ProviderShape` value under SHAPES that
names its environment fields, describes how it talks to the upstream
API, and exposes a lightweight credential test. `eval_command` and
`doctor` talk only to the shape — they never branch on a provider
string.

Shapes themselves are stateless values. All per-invocation config
(deployment name, API version, reasoning flag, claude alias, max image
count, …) flows through the `extras` dict passed to `run()` and
`credential_test()`. That keeps this module cheap to import and avoids
leaking a shape's internals (messages, request bodies, subprocess
argv) across the boundary.

Five shapes are declared: three concrete (`azure-openai`, `azure-maas`,
`claude-cli`) and two reserved (`openai`, `anthropic`) whose `run()`
raises `NotImplementedError`. Reserved shapes hold the namespace stable
so the SHAPES dict does not churn when native-SDK implementations
eventually pass calibration.
"""

from __future__ import annotations

from cold_read.errors import InvocationError
from cold_read.providers.shape import (
    CredentialsMissingError,
    CredentialTestFn,
    CredentialTestResult,
    EnvField,
    EvalResult,
    ProviderShape,
    RunFn,
)


def _reserved_run(name: str, advice: str) -> RunFn:
    def _run(prompt_text: str, images: list, extras: dict) -> EvalResult:
        # InvocationError so the bucket-labeled CLI formatter prints
        # `[invocation] ...` instead of dumping a raw NotImplementedError
        # traceback if a reserved shape is ever reached via a hand-edited
        # config.
        raise InvocationError(f"{name} shape is reserved; {advice}")

    return _run


def _reserved_credential_test(name: str) -> CredentialTestFn:
    def _test(extras: dict) -> CredentialTestResult:
        return CredentialTestResult(
            ok=False, reason=f"{name} shape is reserved; not implemented"
        )

    return _test


def _reserved(name: str, advice: str) -> ProviderShape:
    return ProviderShape(
        name=name,
        credential_fields=(),
        requires_deployment_map=False,
        run=_reserved_run(name, advice),
        credential_test=_reserved_credential_test(name),
    )


# Concrete shapes are registered at import time. Each submodule owns a
# single SHAPE value.
from cold_read.providers import azure_maas as _azure_maas  # noqa: E402
from cold_read.providers import azure_openai as _azure_openai  # noqa: E402
from cold_read.providers import claude_cli as _claude_cli  # noqa: E402

SHAPES: dict[str, ProviderShape] = {
    "azure-openai": _azure_openai.SHAPE,
    "azure-maas": _azure_maas.SHAPE,
    "claude-cli": _claude_cli.SHAPE,
    "openai": _reserved(
        "openai", "use azure-openai for calibrated GPT models"
    ),
    "anthropic": _reserved(
        "anthropic", "use claude-cli"
    ),
}

RESERVED_SHAPES = frozenset({"openai", "anthropic"})


def is_reserved(shape_name: str) -> bool:
    return shape_name in RESERVED_SHAPES


__all__ = [
    "EnvField",
    "EvalResult",
    "CredentialTestResult",
    "ProviderShape",
    "CredentialsMissingError",
    "SHAPES",
    "RESERVED_SHAPES",
    "is_reserved",
]
