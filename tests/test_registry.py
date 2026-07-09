"""Tests for the alias→shape model registry and resolve()."""

from __future__ import annotations

import pytest

from cold_read.config import Config, ProviderConfig
from cold_read.registry import (
    MODELS,
    ResolvedModel,
    UnknownModelError,
    UnresolvedDeploymentError,
    list_aliases,
    resolve,
)


def _config_with_maps() -> Config:
    return Config(
        default_model="gpt52",
        providers={
            "azure-openai": ProviderConfig(deployment_map={"gpt52": "gpt-52-chat"}),
            "azure-maas": ProviderConfig(
                deployment_map={"grok4": "grok-4-fast-reasoning"}
            ),
        },
    )


def test_list_aliases_returns_the_registered_models():
    assert list_aliases() == [
        "claude-opus",
        "claude-sonnet",
        "gpt52",
        "gpt56",
        "grok4",
    ]


def test_resolve_azure_openai_pulls_deployment_from_config():
    resolved = resolve("gpt52", _config_with_maps())

    assert isinstance(resolved, ResolvedModel)
    assert resolved.alias == "gpt52"
    assert resolved.shape.name == "azure-openai"
    assert resolved.deployment == "gpt-52-chat"
    # API version and reasoning are intrinsic extras, carried into the
    # shape invocation.
    assert resolved.extras["api_version"] == "2024-12-01-preview"
    assert resolved.extras["reasoning"] is True
    # gpt-52-chat only accepts "medium"; gpt56/sol carries "high".
    assert resolved.extras["reasoning_effort"] == "medium"
    assert resolved.extras["deployment"] == "gpt-52-chat"


def test_resolve_gpt56_carries_high_reasoning_effort():
    config = Config(
        providers={
            "azure-openai": ProviderConfig(deployment_map={"gpt56": "gpt-56-sol"})
        },
    )
    resolved = resolve("gpt56", config)

    assert resolved.shape.name == "azure-openai"
    assert resolved.deployment == "gpt-56-sol"
    assert resolved.extras["reasoning_effort"] == "high"


def test_resolve_azure_maas_pulls_deployment_from_config():
    resolved = resolve("grok4", _config_with_maps())

    assert resolved.shape.name == "azure-maas"
    assert resolved.deployment == "grok-4-fast-reasoning"
    assert resolved.extras["deployment"] == "grok-4-fast-reasoning"


def test_resolve_claude_cli_does_not_depend_on_config():
    # claude-cli has no deployment_map — an empty Config should still resolve.
    resolved = resolve("claude-sonnet", Config())

    assert resolved.shape.name == "claude-cli"
    assert resolved.deployment is None
    assert resolved.extras["claude_alias"] == "sonnet"
    assert "deployment" not in resolved.extras


def test_resolve_claude_opus_uses_opus_alias():
    resolved = resolve("claude-opus", Config())
    assert resolved.extras["claude_alias"] == "opus"


def test_resolve_unknown_alias_raises_with_known_aliases_listed():
    with pytest.raises(UnknownModelError) as exc_info:
        resolve("unknown", Config())
    msg = str(exc_info.value)
    assert "unknown" in msg
    for alias in MODELS:
        assert alias in msg


def test_resolve_missing_deployment_map_raises_clear_error():
    # Azure-MaaS alias, but config has no deployment map entry.
    with pytest.raises(UnresolvedDeploymentError) as exc_info:
        resolve("grok4", Config())
    msg = str(exc_info.value)
    # Must name the alias, the shape, and the fix path.
    assert "grok4" in msg
    assert "azure-maas" in msg
    assert "deployment_map" in msg
    assert "resume-cold-read init" in msg or "config.toml" in msg


def test_resolve_empty_deployment_map_raises():
    config = Config(
        providers={"azure-openai": ProviderConfig(deployment_map={})}
    )
    with pytest.raises(UnresolvedDeploymentError):
        resolve("gpt52", config)


def test_reserved_shapes_have_no_aliases_in_models():
    shape_names = {entry.shape for entry in MODELS.values()}
    assert "openai" not in shape_names
    assert "anthropic" not in shape_names
