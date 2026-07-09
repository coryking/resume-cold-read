"""Tests for the `azure-openai` provider shape."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cold_read.providers import azure_openai, SHAPES
from cold_read.providers.shape import (
    CredentialsMissingError,
    CredentialTestResult,
    EvalResult,
)


@pytest.fixture
def env(monkeypatch):
    """Stand up the two Azure OpenAI creds in the process env.

    Also clears `COLD_READ_REASONING_EFFORT` so the effort assertions below
    exercise the per-model registry value, not whatever the runner's shell
    happens to export.
    """
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com/")
    monkeypatch.delenv("COLD_READ_REASONING_EFFORT", raising=False)


@pytest.fixture
def tiny_png(tmp_path):
    """Write a minimal 1x1 PNG so base64 encoding has real bytes to chew on."""
    p = tmp_path / "page-1.png"
    p.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x04\x1d"
        b"\x12\xb5\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return p


def _fake_response(content: str = "hello", prompt_tokens: int = 100, completion_tokens: int = 50):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        ),
    )


def test_run_passes_deployment_as_model_and_includes_base64_image(env, tiny_png, mocker):
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _fake_response()
    mocker.patch.object(azure_openai, "AzureOpenAI", return_value=fake_client)

    result = azure_openai.run(
        "prompt goes here",
        [tiny_png],
        extras={
            "deployment": "gpt-56-sol",
            "api_version": "2024-12-01-preview",
            "reasoning": True,
            "reasoning_effort": "high",
        },
    )

    assert isinstance(result, EvalResult)
    assert result.content == "hello"
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 50

    fake_client.chat.completions.create.assert_called_once()
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-56-sol"
    # Per-model effort from extras is forwarded verbatim.
    assert kwargs["reasoning_effort"] == "high"
    assert kwargs["max_completion_tokens"] == 16384
    # Image should be base64-encoded into messages, not passed as a path.
    parts = kwargs["messages"][0]["content"]
    image_part = next(p for p in parts if p["type"] == "image_url")
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


def test_run_without_reasoning_omits_reasoning_effort(env, tiny_png, mocker):
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _fake_response()
    mocker.patch.object(azure_openai, "AzureOpenAI", return_value=fake_client)

    azure_openai.run(
        "x",
        [tiny_png],
        extras={
            "deployment": "gpt-52-chat",
            "api_version": "2024-12-01-preview",
            "reasoning": False,
        },
    )

    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert "reasoning_effort" not in kwargs


def test_run_missing_creds_raises_credentials_missing_error(monkeypatch, tiny_png):
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)

    with pytest.raises(CredentialsMissingError) as exc_info:
        azure_openai.run(
            "x",
            [tiny_png],
            extras={"deployment": "gpt-52-chat", "api_version": "2024-12-01-preview"},
        )
    msg = str(exc_info.value)
    assert "AZURE_OPENAI_API_KEY" in msg
    assert "AZURE_OPENAI_ENDPOINT" in msg


def test_credential_test_happy_path(env, mocker):
    fake_client = mocker.MagicMock()
    fake_client.models.list.return_value = []
    mocker.patch.object(azure_openai, "AzureOpenAI", return_value=fake_client)

    result = azure_openai.credential_test({"api_version": "2024-12-01-preview"})

    assert isinstance(result, CredentialTestResult)
    assert result.ok is True


def test_credential_test_returns_ok_false_on_upstream_error(env, mocker):
    fake_client = mocker.MagicMock()
    fake_client.models.list.side_effect = RuntimeError("401 Unauthorized")
    mocker.patch.object(azure_openai, "AzureOpenAI", return_value=fake_client)

    result = azure_openai.credential_test({"api_version": "2024-12-01-preview"})

    assert result.ok is False
    assert "401" in (result.reason or "")


def test_credential_test_returns_ok_false_when_env_missing(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)

    result = azure_openai.credential_test({"api_version": "2024-12-01-preview"})

    assert result.ok is False
    assert "AZURE_OPENAI_API_KEY" in (result.reason or "")


def test_shape_registration():
    shape = SHAPES["azure-openai"]
    assert shape.name == "azure-openai"
    assert shape.requires_deployment_map is True
    names = [f.name for f in shape.credential_fields]
    assert names == ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"]
    # API key must be marked secret so the wizard/doctor handle it correctly.
    key_field = next(f for f in shape.credential_fields if f.name == "AZURE_OPENAI_API_KEY")
    assert key_field.secret is True
