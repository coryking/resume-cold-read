"""Model registry: alias → shape + shape-specific defaults.

`MODELS` names the aliases that ship today. Each entry only holds
what is intrinsic to the model itself (provider shape, API version,
reasoning flag, claude alias). Deployment names are user-owned state
(bucket 2) and live in `config.toml`; `resolve()` joins the two at call
time so the code never ships a maintainer-specific deployment string.

Reserved shapes (`openai`, `anthropic`) are in `providers.SHAPES` but
have no registered aliases here — they are not reachable via `resolve`
and `--list-models` excludes them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cold_read.config import Config
from cold_read.providers import SHAPES
from cold_read.providers.shape import ProviderShape


@dataclass(frozen=True)
class ModelEntry:
    """A registered alias, independent of any user config."""

    shape: str
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedModel:
    """Alias + shape + deployment + extras, ready to pass to `shape.run()`."""

    alias: str
    shape: ProviderShape
    deployment: str | None
    extras: dict[str, Any]


class UnknownModelError(KeyError):
    """Raised when an alias is not registered in MODELS."""


class UnresolvedDeploymentError(RuntimeError):
    """Raised when a deployment-requiring shape has no mapping for the alias."""


MODELS: dict[str, ModelEntry] = {
    "gpt52": ModelEntry(
        shape="azure-openai",
        extras={
            "api_version": "2024-12-01-preview",
            "reasoning": True,
            "reasoning_effort": "medium",
        },
    ),
    "gpt56": ModelEntry(
        shape="azure-openai",
        extras={
            "api_version": "2024-12-01-preview",
            "reasoning": True,
            "reasoning_effort": "high",
        },
    ),
    "grok4": ModelEntry(
        shape="azure-maas",
        extras={},
    ),
    "claude-sonnet": ModelEntry(
        shape="claude-cli",
        extras={"claude_alias": "sonnet"},
    ),
    "claude-opus": ModelEntry(
        shape="claude-cli",
        extras={"claude_alias": "opus"},
    ),
}


def resolve(alias: str, config: Config) -> ResolvedModel:
    """Join an alias with the user's config to produce a runnable model.

    Raises `UnknownModelError` for unregistered aliases, or
    `UnresolvedDeploymentError` when the alias's shape requires a
    `deployment_map` entry that the user has not set up yet.
    """
    if alias not in MODELS:
        available = ", ".join(sorted(MODELS))
        raise UnknownModelError(
            f"Unknown model '{alias}'. Available: {available}"
        )

    entry = MODELS[alias]
    shape = SHAPES[entry.shape]

    deployment: str | None = None
    if shape.requires_deployment_map:
        provider_cfg = config.providers.get(entry.shape)
        if provider_cfg is None or alias not in provider_cfg.deployment_map:
            raise UnresolvedDeploymentError(
                f"No deployment configured for '{alias}' on the '{entry.shape}' "
                f"shape. Add `[providers.\"{entry.shape}\"] deployment_map.{alias}` "
                f"to config.toml, or run `resume-cold-read init`."
            )
        deployment = provider_cfg.deployment_map[alias]

    resolved_extras: dict[str, Any] = dict(entry.extras)
    if deployment is not None:
        resolved_extras["deployment"] = deployment

    return ResolvedModel(
        alias=alias,
        shape=shape,
        deployment=deployment,
        extras=resolved_extras,
    )


def list_aliases() -> list[str]:
    """Return the registered aliases in a deterministic order."""
    return sorted(MODELS)


def aliases_for_shape(shape_name: str) -> list[str]:
    """Return registered aliases that resolve to a given shape, sorted."""
    return sorted(
        alias for alias, entry in MODELS.items() if entry.shape == shape_name
    )
