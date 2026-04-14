"""Tests for the `azure-maas` provider shape."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cold_read.providers import azure_maas, SHAPES
from cold_read.providers.shape import (
    CredentialsMissingError,
    CredentialTestResult,
    EvalResult,
)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AZURE_MAAS_API_KEY", "test-maas-key")
    monkeypatch.setenv(
        "AZURE_MAAS_ENDPOINT", "https://test.services.ai.azure.com"
    )


@pytest.fixture
def tiny_png(tmp_path):
    p = tmp_path / "page-1.png"
    p.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x04\x1d"
        b"\x12\xb5\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return p


def _fake_response(content: str = "grok-says-ok"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


def test_run_uses_openai_v1_base_url_and_deployment(env, tiny_png, mocker):
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _fake_response()
    ctor = mocker.patch.object(azure_maas, "OpenAI", return_value=fake_client)

    result = azure_maas.run(
        "x",
        [tiny_png],
        extras={"deployment": "grok-4-fast-reasoning"},
    )

    assert isinstance(result, EvalResult)
    ctor.assert_called_once()
    call_kwargs = ctor.call_args.kwargs
    # The `/openai/v1/` suffix is the whole point of this shape.
    assert call_kwargs["base_url"] == "https://test.services.ai.azure.com/openai/v1/"

    fake_client.chat.completions.create.assert_called_once()
    send_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert send_kwargs["model"] == "grok-4-fast-reasoning"
    assert send_kwargs["max_tokens"] == 16384  # MaaS uses max_tokens, not max_completion_tokens


def test_run_trims_trailing_slash_on_endpoint(monkeypatch, tiny_png, mocker):
    monkeypatch.setenv("AZURE_MAAS_API_KEY", "k")
    monkeypatch.setenv(
        "AZURE_MAAS_ENDPOINT", "https://test.services.ai.azure.com/"
    )
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _fake_response()
    ctor = mocker.patch.object(azure_maas, "OpenAI", return_value=fake_client)

    azure_maas.run("x", [tiny_png], extras={"deployment": "grok-4-fast-reasoning"})

    assert ctor.call_args.kwargs["base_url"] == (
        "https://test.services.ai.azure.com/openai/v1/"
    )


def test_run_missing_creds_raises(monkeypatch, tiny_png):
    monkeypatch.delenv("AZURE_MAAS_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_MAAS_ENDPOINT", raising=False)

    with pytest.raises(CredentialsMissingError) as exc_info:
        azure_maas.run("x", [tiny_png], extras={"deployment": "grok-4-fast-reasoning"})
    msg = str(exc_info.value)
    assert "AZURE_MAAS_API_KEY" in msg
    assert "AZURE_MAAS_ENDPOINT" in msg


def test_credential_test_happy_path(env, mocker):
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _fake_response("ok")
    mocker.patch.object(azure_maas, "OpenAI", return_value=fake_client)

    result = azure_maas.credential_test({"deployment": "grok-4-fast-reasoning"})
    assert result.ok is True
    # Must pass deployment as model on the probe call.
    assert (
        fake_client.chat.completions.create.call_args.kwargs["model"]
        == "grok-4-fast-reasoning"
    )
    assert fake_client.chat.completions.create.call_args.kwargs["max_tokens"] == 1


def test_credential_test_requires_deployment_extra(env):
    result = azure_maas.credential_test({})
    assert result.ok is False
    assert "deployment" in (result.reason or "").lower()


def test_credential_test_returns_ok_false_on_401(env, mocker):
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.side_effect = RuntimeError("401 Unauthorized")
    mocker.patch.object(azure_maas, "OpenAI", return_value=fake_client)

    result = azure_maas.credential_test({"deployment": "grok-4-fast-reasoning"})
    assert result.ok is False
    assert "401" in (result.reason or "")


def test_shape_registration():
    shape = SHAPES["azure-maas"]
    assert shape.name == "azure-maas"
    assert shape.requires_deployment_map is True
    names = [f.name for f in shape.credential_fields]
    assert names == ["AZURE_MAAS_API_KEY", "AZURE_MAAS_ENDPOINT"]
