"""Tests for the `resume-cold-read init` wizard."""

from __future__ import annotations

import os
from types import SimpleNamespace

import httpx
import pytest

from cold_read import config as _config
from cold_read import wizard


@pytest.fixture
def fake_dirs(monkeypatch, tmp_path):
    cfg = tmp_path / "config"
    data = tmp_path / "data"
    monkeypatch.setattr(
        _config.platformdirs, "user_config_dir", lambda app_name: str(cfg)
    )
    monkeypatch.setattr(
        _config.platformdirs, "user_data_dir", lambda app_name: str(data)
    )
    monkeypatch.chdir(tmp_path)
    # Clean credential slate so tests don't inherit whatever the dev shell has.
    for var in (
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_MAAS_API_KEY",
        "AZURE_MAAS_ENDPOINT",
    ):
        monkeypatch.delenv(var, raising=False)
    return cfg, data, tmp_path


class _Prompter:
    """Deterministic stand-in for rich.prompt.{Prompt,Confirm}.ask().

    Each list is drained in call order. Tests fail loudly if the wizard
    prompts more times than the script provides.
    """

    def __init__(
        self,
        prompts: list[object],
        confirms: list[bool] | None = None,
    ) -> None:
        self._prompts = iter(prompts)
        self._confirms = iter(confirms or [])

    def ask(self, *args, **kwargs):
        try:
            return next(self._prompts)
        except StopIteration as exc:
            raise AssertionError(
                f"Prompt.ask called with args={args!r} kwargs={kwargs!r} but the "
                f"test script ran out of answers"
            ) from exc

    def confirm(self, *args, **kwargs):
        try:
            return next(self._confirms)
        except StopIteration as exc:
            raise AssertionError(
                f"Confirm.ask called with args={args!r} kwargs={kwargs!r} but the "
                f"test script ran out of answers"
            ) from exc


def _install_prompter(monkeypatch, prompter: _Prompter):
    monkeypatch.setattr("rich.prompt.Prompt.ask", prompter.ask)
    monkeypatch.setattr("rich.prompt.Confirm.ask", prompter.confirm)


# -- list_vision_deployments (listing HTTP call) --------------------------


def test_try_list_vision_deployments_filters_to_vision_families(mocker):
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "data": [
                {"id": "gpt-52-chat", "model": "gpt-5.2-chat"},
                {"id": "embedding-3", "model": "text-embedding-3-large"},
                {"id": "gpt-4o-ga", "model": "gpt-4o"},
            ]
        },
    )
    client = mocker.MagicMock()
    client.__enter__.return_value = client
    client.get.return_value = response
    mocker.patch.object(wizard.httpx, "Client", return_value=client)

    results = wizard._try_list_vision_deployments(
        "https://test.openai.azure.com/", "k"
    )

    ids = [d["id"] for d in results]
    assert ids == ["gpt-52-chat", "gpt-4o-ga"]
    # Pinned API version is sent as a query param
    sent_params = client.get.call_args.kwargs["params"]
    assert sent_params["api-version"] == wizard.LISTING_API_VERSION
    # api-key is used as the auth header
    assert client.get.call_args.kwargs["headers"]["api-key"] == "k"


def test_try_list_vision_deployments_returns_empty_on_connect_timeout(mocker):
    client = mocker.MagicMock()
    client.__enter__.return_value = client
    client.get.side_effect = httpx.ConnectTimeout("boom")
    mocker.patch.object(wizard.httpx, "Client", return_value=client)

    assert wizard._try_list_vision_deployments("https://x", "k") == []


def test_try_list_vision_deployments_returns_empty_on_401(mocker):
    response = SimpleNamespace(
        raise_for_status=lambda: (_ for _ in ()).throw(
            httpx.HTTPStatusError(
                "401",
                request=httpx.Request("GET", "https://x"),
                response=httpx.Response(401),
            )
        ),
        json=lambda: {},
    )
    client = mocker.MagicMock()
    client.__enter__.return_value = client
    client.get.return_value = response
    mocker.patch.object(wizard.httpx, "Client", return_value=client)

    assert wizard._try_list_vision_deployments("https://x", "k") == []


# -- Endpoint validation --------------------------------------------------


def test_endpoint_prompt_rejects_http_then_accepts_https(monkeypatch):
    field = wizard.EnvField(
        "AZURE_OPENAI_ENDPOINT", "Azure OpenAI endpoint", secret=False
    )
    answers = ["http://insecure.com/", "  https://ok.com/  "]
    prompter = _Prompter(answers, confirms=[])
    monkeypatch.setattr("rich.prompt.Prompt.ask", prompter.ask)

    value = wizard._prompt_endpoint(field, existing="")
    # Whitespace is stripped; http:// is rejected and re-prompted.
    assert value == "https://ok.com/"


# -- azure-openai full flow -----------------------------------------------


def _stub_shape_credential_test(monkeypatch, shape_name: str, ok: bool, reason: str = ""):
    """Swap SHAPES[shape_name] with a copy whose credential_test is canned."""
    from cold_read.providers import SHAPES
    from cold_read.providers.shape import CredentialTestResult, ProviderShape
    original = SHAPES[shape_name]
    stub = ProviderShape(
        name=original.name,
        credential_fields=original.credential_fields,
        requires_deployment_map=original.requires_deployment_map,
        run=original.run,
        credential_test=lambda extras: CredentialTestResult(ok=ok, reason=reason),
    )
    monkeypatch.setitem(SHAPES, shape_name, stub)


def _mock_listing_success(mocker, deployments):
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"data": deployments},
    )
    client = mocker.MagicMock()
    client.__enter__.return_value = client
    client.get.return_value = response
    mocker.patch.object(wizard.httpx, "Client", return_value=client)


def test_azure_openai_flow_writes_env_and_config_when_test_passes(
    fake_dirs, monkeypatch, mocker
):
    cfg_root, _, _ = fake_dirs

    _mock_listing_success(
        mocker, [{"id": "gpt-52-chat", "model": "gpt-5.2-chat"}]
    )
    _stub_shape_credential_test(monkeypatch, "azure-openai", ok=True)

    # Wizard interaction:
    #   shape choice -> "azure-openai"
    #   endpoint     -> https://real.openai.azure.com/
    #   api key      -> "k"
    #   pick #1 for gpt52
    #   default_model -> gpt52
    #   another provider? -> No
    prompter = _Prompter(
        prompts=[
            "azure-openai",
            "k",
            "https://real.openai.azure.com/",
            "1",
            "gpt52",
        ],
        confirms=[False],
    )
    _install_prompter(monkeypatch, prompter)

    wizard.init_command()

    env_file = cfg_root / ".env"
    assert env_file.is_file()
    env = env_file.read_text()
    assert "AZURE_OPENAI_API_KEY=k" in env
    assert "AZURE_OPENAI_ENDPOINT=https://real.openai.azure.com/" in env

    cfg = _config.read_config()
    assert cfg.default_model == "gpt52"
    assert cfg.providers["azure-openai"].deployment_map == {"gpt52": "gpt-52-chat"}


def test_azure_openai_flow_does_not_write_when_credential_test_fails_and_user_skips(
    fake_dirs, monkeypatch, mocker
):
    cfg_root, _, _ = fake_dirs

    _mock_listing_success(
        mocker, [{"id": "gpt-52-chat", "model": "gpt-5.2-chat"}]
    )
    _stub_shape_credential_test(
        monkeypatch, "azure-openai", ok=False, reason="401 Unauthorized"
    )

    prompter = _Prompter(
        prompts=[
            "azure-openai",
            "wrong-key",
            "https://real.openai.azure.com/",
            "1",
            # No default_model prompt will be asked because nothing was
            # configured; _prompt_default_model skips when eligible == [].
        ],
        confirms=[
            False,  # "Re-enter credentials?" → No, give up this shape
            False,  # "Configure another provider?" → No
        ],
    )
    _install_prompter(monkeypatch, prompter)

    wizard.init_command()

    # Nothing should have been written — no default_model change, no provider
    # added, so the write-on-dirty path stays silent.
    assert not _config.config_file().is_file()


def test_wizard_preserves_existing_env_and_provider_sections(
    fake_dirs, monkeypatch, mocker
):
    cfg_root, _, _ = fake_dirs

    # Seed pre-existing config + env from a prior session.
    cfg_root.mkdir(parents=True, exist_ok=True)
    pre_env = cfg_root / ".env"
    pre_env.write_text("SOME_OTHER_VAR=preserve-me\n")
    pre_cfg = _config.Config(
        default_model="grok4",
        providers={
            "azure-maas": _config.ProviderConfig(
                deployment_map={"grok4": "grok-4-fast-reasoning"}
            ),
        },
    )
    _config.write_config(pre_cfg)

    _mock_listing_success(
        mocker, [{"id": "gpt-52-chat", "model": "gpt-5.2-chat"}]
    )
    _stub_shape_credential_test(monkeypatch, "azure-openai", ok=True)

    prompter = _Prompter(
        prompts=[
            "azure-openai",
            "k",
            "https://real.openai.azure.com/",
            "1",
            "gpt52",  # pick default_model among the now-two resolvable aliases
        ],
        confirms=[False],  # no further providers
    )
    _install_prompter(monkeypatch, prompter)

    wizard.init_command()

    # Pre-existing env var survives
    env = pre_env.read_text()
    assert "SOME_OTHER_VAR=preserve-me" in env
    assert "AZURE_OPENAI_API_KEY=k" in env

    cfg = _config.read_config()
    # Both providers present
    assert cfg.providers["azure-maas"].deployment_map == {
        "grok4": "grok-4-fast-reasoning"
    }
    assert cfg.providers["azure-openai"].deployment_map == {
        "gpt52": "gpt-52-chat"
    }


def test_claude_cli_flow_when_claude_missing(fake_dirs, monkeypatch):
    _stub_shape_credential_test(
        monkeypatch, "claude-cli", ok=False, reason="`claude` CLI not found on PATH"
    )

    prompter = _Prompter(
        prompts=["claude-cli"],
        confirms=[False],  # after the unavailable shape, no more providers
    )
    _install_prompter(monkeypatch, prompter)

    wizard.init_command()

    # claude-cli was not credential-tested OK and has no existing provider
    # entry — the default_model prompt is skipped and no config.toml is
    # created.
    assert not _config.config_file().is_file()


# -- Static helpers -------------------------------------------------------


def test_is_vision_family_allows_gpt_families():
    assert wizard._is_vision_family("gpt-5.2-chat")
    assert wizard._is_vision_family("gpt-4o")
    assert wizard._is_vision_family("gpt-4.1-mini")


def test_is_vision_family_rejects_non_vision_models():
    assert not wizard._is_vision_family("text-embedding-3-large")
    assert not wizard._is_vision_family("gpt-3.5-turbo")
    assert not wizard._is_vision_family(None)
    assert not wizard._is_vision_family("")


def test_aliases_for_shape_groups_by_shape():
    aliases = wizard._aliases_for_shape("claude-cli")
    assert set(aliases) == {"claude-sonnet", "claude-opus"}
    assert wizard._aliases_for_shape("azure-openai") == ["gpt52"]
    assert wizard._aliases_for_shape("azure-maas") == ["grok4"]


def test_write_env_file_is_mode_0600(fake_dirs):
    wizard._write_env_file({"A": "1", "B": "2"})
    path = _config.env_file()
    assert path.is_file()
    assert oct(path.stat().st_mode)[-3:] == "600"
    text = path.read_text()
    assert "A=1" in text
    assert "B=2" in text
