"""Tests for the `resume-cold-read doctor` command."""

from __future__ import annotations

import pytest

from cold_read import config as _config
from cold_read import doctor
from cold_read import prompts as _prompts


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
    # Drop all Azure creds from the test shell so doctor is deterministic.
    for var in (
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_MAAS_API_KEY",
        "AZURE_MAAS_ENDPOINT",
        "AZURE_PRIMARY_API_KEY",
        "AZURE_PRIMARY_ENDPOINT",
        "AZURE_SECONDARY_API_KEY",
        "AZURE_SECONDARY_ENDPOINT",
    ):
        monkeypatch.delenv(var, raising=False)
    return cfg, data, tmp_path


def _stub_shape(monkeypatch, shape_name, ok, reason=""):
    from cold_read.providers import SHAPES
    from cold_read.providers.shape import CredentialTestResult, ProviderShape
    orig = SHAPES[shape_name]
    monkeypatch.setitem(
        SHAPES,
        shape_name,
        ProviderShape(
            name=orig.name,
            credential_fields=orig.credential_fields,
            requires_deployment_map=orig.requires_deployment_map,
            run=orig.run,
            credential_test=lambda extras: CredentialTestResult(ok=ok, reason=reason),
        ),
    )


def _run_doctor():
    """Invoke doctor_command and capture its typer.Exit code."""
    import typer
    try:
        doctor.doctor_command()
    except typer.Exit as e:
        return int(e.exit_code or 0)
    return 0


# -- Install section ------------------------------------------------------


def test_install_green_when_manifest_and_pdftoppm_present(fake_dirs, mocker):
    mocker.patch.object(doctor.shutil, "which", return_value="/opt/poppler/bin/pdftoppm")

    checks = doctor._check_install()

    statuses = [c.status for c in checks]
    assert statuses == [doctor.GREEN, doctor.GREEN]


def test_install_red_when_pdftoppm_missing(fake_dirs, mocker):
    mocker.patch.object(doctor.shutil, "which", return_value=None)

    checks = doctor._check_install()

    pdftoppm_check = [c for c in checks if "pdftoppm" in c.message][0]
    assert pdftoppm_check.status == doctor.RED
    assert "poppler" in pdftoppm_check.message


def test_install_red_when_manifest_unreadable(fake_dirs, mocker):
    mocker.patch.object(doctor.shutil, "which", return_value="/usr/bin/pdftoppm")
    mocker.patch.object(
        _prompts, "load_manifest", side_effect=RuntimeError("packaged resource gone")
    )

    checks = doctor._check_install()

    assert checks[0].status == doctor.RED
    assert "uv tool install --force" in checks[0].message


# -- Config section -------------------------------------------------------


def test_config_yellow_when_no_env_or_config_toml(fake_dirs):
    checks = doctor._check_config()

    statuses = [c.status for c in checks]
    # config_dir is created on first access → GREEN
    assert statuses[0] == doctor.GREEN
    # .env absent → YELLOW
    assert statuses[1] == doctor.YELLOW
    # config.toml absent → YELLOW
    assert statuses[2] == doctor.YELLOW


def test_config_yellow_flags_deprecated_env_vars(fake_dirs, monkeypatch):
    monkeypatch.setenv("AZURE_PRIMARY_API_KEY", "legacy")

    checks = doctor._check_config()

    deprecated_check = [c for c in checks if "AZURE_PRIMARY_API_KEY" in c.message][0]
    assert deprecated_check.status == doctor.YELLOW
    assert "Rename" in deprecated_check.message


# -- Providers + Models section -------------------------------------------


def test_providers_yellow_when_env_missing(fake_dirs):
    results, checks = doctor._check_providers(_config.Config())

    # azure-openai and azure-maas both YELLOW not-configured
    azure_openai = [c for c in checks if c.message.startswith("azure-openai")][0]
    azure_maas = [c for c in checks if c.message.startswith("azure-maas")][0]
    assert azure_openai.status == doctor.YELLOW
    assert azure_maas.status == doctor.YELLOW
    assert results["azure-openai"] is None
    assert results["azure-maas"] is None


def test_providers_green_when_creds_set_and_shape_test_ok(
    fake_dirs, monkeypatch
):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://x/")
    _stub_shape(monkeypatch, "azure-openai", ok=True)
    _stub_shape(monkeypatch, "claude-cli", ok=True)

    results, checks = doctor._check_providers(_config.Config())

    azure_openai = [c for c in checks if c.message.startswith("azure-openai")][0]
    assert azure_openai.status == doctor.GREEN
    assert results["azure-openai"] is True
    assert results["claude-cli"] is True


def test_providers_red_when_shape_test_fails(fake_dirs, monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://x/")
    _stub_shape(monkeypatch, "azure-openai", ok=False, reason="401")

    results, checks = doctor._check_providers(_config.Config())

    azure_openai = [c for c in checks if c.message.startswith("azure-openai")][0]
    assert azure_openai.status == doctor.RED
    assert "401" in azure_openai.message
    assert results["azure-openai"] is False


def test_models_yellow_without_deployment_map(fake_dirs):
    results, _ = doctor._check_providers(_config.Config())
    checks = doctor._check_models(_config.Config(), results)

    gpt52 = [c for c in checks if c.message.startswith("gpt52")][0]
    assert gpt52.status == doctor.YELLOW


def test_models_green_when_shape_healthy_and_map_present(fake_dirs, monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://x/")
    _stub_shape(monkeypatch, "azure-openai", ok=True)

    cfg = _config.Config(
        default_model="gpt52",
        providers={
            "azure-openai": _config.ProviderConfig(
                deployment_map={"gpt52": "gpt-52-chat"}
            )
        },
    )
    provider_results, _ = doctor._check_providers(cfg)
    checks = doctor._check_models(cfg, provider_results)

    gpt52 = [c for c in checks if c.message.startswith("gpt52")][0]
    assert gpt52.status == doctor.GREEN
    # The default marker must surface somewhere on the default alias's line.
    assert "default" in gpt52.message


# -- Exit code + full run -------------------------------------------------


def test_doctor_exits_1_on_clean_machine(fake_dirs, monkeypatch, mocker):
    mocker.patch.object(doctor.shutil, "which", return_value="/usr/bin/pdftoppm")
    _stub_shape(monkeypatch, "claude-cli", ok=False, reason="not on PATH")
    # No env creds, no config → no green model.
    assert _run_doctor() == 1


def test_doctor_exits_0_with_healthy_gpt52(fake_dirs, monkeypatch, mocker):
    mocker.patch.object(doctor.shutil, "which", return_value="/usr/bin/pdftoppm")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://x/")
    _stub_shape(monkeypatch, "azure-openai", ok=True)
    _stub_shape(monkeypatch, "claude-cli", ok=False, reason="not on PATH")

    cfg = _config.Config(
        default_model="gpt52",
        providers={
            "azure-openai": _config.ProviderConfig(
                deployment_map={"gpt52": "gpt-52-chat"}
            )
        },
    )
    _config.write_config(cfg)

    # Still need an .env present — but load_env reads at CLI callback level.
    # For the exit test we just assert the exit code from a direct call.
    assert _run_doctor() == 0


def test_doctor_exits_1_when_pdftoppm_missing_even_with_green_model(
    fake_dirs, monkeypatch, mocker
):
    mocker.patch.object(doctor.shutil, "which", return_value=None)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://x/")
    _stub_shape(monkeypatch, "azure-openai", ok=True)

    cfg = _config.Config(
        default_model="gpt52",
        providers={
            "azure-openai": _config.ProviderConfig(
                deployment_map={"gpt52": "gpt-52-chat"}
            )
        },
    )
    _config.write_config(cfg)

    # Install section has a red entry → exit 1 regardless of model health.
    assert _run_doctor() == 1
