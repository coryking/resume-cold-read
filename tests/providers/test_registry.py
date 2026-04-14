"""Tests for the SHAPES registry and reserved-shape behavior."""

from __future__ import annotations

import pytest

from cold_read.errors import InvocationError
from cold_read.providers import SHAPES, is_reserved


def test_all_expected_shapes_registered():
    assert set(SHAPES.keys()) == {
        "azure-openai",
        "azure-maas",
        "claude-cli",
        "openai",
        "anthropic",
    }


@pytest.mark.parametrize("name", ["openai", "anthropic"])
def test_reserved_shapes_are_marked_reserved(name):
    assert is_reserved(name)


@pytest.mark.parametrize("name", ["azure-openai", "azure-maas", "claude-cli"])
def test_concrete_shapes_are_not_reserved(name):
    assert not is_reserved(name)


def test_reserved_openai_run_raises_with_documented_message():
    # Bucket-labeled InvocationError so the CLI formatter prints
    # `[invocation] ...` instead of dumping a raw traceback.
    with pytest.raises(InvocationError) as exc_info:
        SHAPES["openai"].run("x", [], {})
    assert "openai shape is reserved" in str(exc_info.value)
    assert "azure-openai" in str(exc_info.value)


def test_reserved_anthropic_run_raises_with_documented_message():
    with pytest.raises(InvocationError) as exc_info:
        SHAPES["anthropic"].run("x", [], {})
    assert "anthropic shape is reserved" in str(exc_info.value)
    assert "claude-cli" in str(exc_info.value)


def test_reserved_credential_test_returns_not_ok():
    for name in ("openai", "anthropic"):
        result = SHAPES[name].credential_test({})
        assert result.ok is False
