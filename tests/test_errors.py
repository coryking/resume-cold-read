"""Tests for bucket-labeled errors and the CLI formatter boundary."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cold_read import config as _config
from cold_read.cli import app
from cold_read.errors import (
    ColdReadError,
    InvocationError,
    PackageResourceError,
    UserConfigError,
)

runner = CliRunner()


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
    for var in (
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_MAAS_API_KEY",
        "AZURE_MAAS_ENDPOINT",
    ):
        monkeypatch.delenv(var, raising=False)
    return cfg, data, tmp_path


# -- Exception class hierarchy --------------------------------------------


def test_package_resource_error_exit_code_is_1():
    exc = PackageResourceError("missing thing", suggestion="reinstall")
    assert isinstance(exc, ColdReadError)
    assert exc.exit_code == 1
    assert exc.label == "package"
    assert exc.message == "missing thing"
    assert exc.suggestion == "reinstall"


def test_user_config_error_exit_code_is_1():
    exc = UserConfigError("bad config", suggestion="run init")
    assert exc.exit_code == 1
    assert exc.label == "config"


def test_invocation_error_exit_code_is_2():
    exc = InvocationError("bad argument")
    assert exc.exit_code == 2
    assert exc.label == "invocation"


# -- CLI formatter boundary ----------------------------------------------
# These exercise the wrapper in cli.py by running the actual commands via
# Typer's CliRunner. The commands return real bucket errors; the wrapper
# must translate them to the right exit code and label.


def test_eval_bucket_2_no_config_exits_1(fake_dirs):
    """On a clean machine with no config.toml and no --model, eval must exit
    1 with a config-bucket label and an init pointer. Uses --prompt
    calibration so the PDF argument isn't required, letting the command
    reach the model-resolution guard."""
    result = runner.invoke(app, ["eval", "--prompt", "calibration"])
    assert result.exit_code == 1, result.output
    assert "[config]" in result.output
    assert "init" in result.output.lower()


def test_eval_bucket_2_unresolved_deployment_exits_1(fake_dirs, tmp_path):
    """`--model gpt52` with no deployment_map entry triggers a config-bucket
    error that names the alias and the shape."""
    # Seed a config.toml that knows about a default_model but no map
    _config.write_config(_config.Config(default_model="gpt52"))
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"")
    result = runner.invoke(app, ["eval", str(pdf), "--model", "gpt52"])
    assert result.exit_code == 1
    assert "[config]" in result.output
    assert "gpt52" in result.output
    assert "deployment" in result.output.lower()


def test_eval_bucket_3_unknown_model_exits_2(fake_dirs, tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"")
    result = runner.invoke(
        app,
        ["eval", str(pdf), "--model", "definitely-not-a-real-alias"],
    )
    assert result.exit_code == 2
    assert "[invocation]" in result.output
    # Must list the known aliases
    assert "gpt52" in result.output


def test_eval_bucket_3_missing_pdf_exits_2(fake_dirs):
    # Configure a default so we get past the no-model guard.
    _config.write_config(
        _config.Config(
            default_model="claude-sonnet",
        )
    )
    result = runner.invoke(app, ["eval", "/nope/does-not-exist.pdf"])
    assert result.exit_code == 2
    assert "[invocation]" in result.output
    assert "not found" in result.output.lower()


def test_eval_bucket_3_missing_jd_exits_2(fake_dirs, tmp_path):
    _config.write_config(_config.Config(default_model="claude-sonnet"))
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"")
    result = runner.invoke(
        app,
        ["eval", str(pdf), "--jd", "/nope/jd.md"],
    )
    assert result.exit_code == 2
    assert "[invocation]" in result.output


def test_eval_bucket_3_unknown_prompt_exits_2(fake_dirs, tmp_path, monkeypatch):
    """--prompt with a bogus id falls through into the loop's _load_prompt
    and raises InvocationError."""
    _config.write_config(
        _config.Config(
            default_model="claude-sonnet",
        )
    )
    # The claude-cli shape has no deployment_map requirement, so resolve
    # succeeds even without config. We just need to drive the command
    # deep enough to hit _load_prompt.
    # Avoid actually calling the shape by intercepting _pdf_to_pngs.
    from cold_read import eval as _eval

    monkeypatch.setattr(_eval, "_pdf_to_pngs", lambda p: [])

    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"")
    result = runner.invoke(
        app,
        ["eval", str(pdf), "--prompt", "definitely-not-a-prompt"],
    )
    assert result.exit_code == 2
    assert "[invocation]" in result.output


def test_list_models_exits_zero_and_is_not_an_error(fake_dirs):
    result = runner.invoke(app, ["eval", "--list-models"])
    # --list-models is a normal success exit, not routed through the
    # error formatter.
    assert result.exit_code == 0
    assert "[package]" not in result.output
    assert "[config]" not in result.output
    assert "[invocation]" not in result.output
