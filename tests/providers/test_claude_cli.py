"""Tests for the `claude-cli` provider shape."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from cold_read.providers import claude_cli, SHAPES
from cold_read.providers.shape import CredentialTestResult, EvalResult


@pytest.fixture
def tiny_png(tmp_path):
    p = tmp_path / "page-1.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    return p


def _ok_subprocess(stdout: str = '{"result": "cli-output"}', returncode: int = 0):
    return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


def test_run_invokes_claude_with_expected_flags_and_strips_claudecode(
    monkeypatch, tiny_png, mocker
):
    monkeypatch.setenv("CLAUDECODE", "1")  # must be stripped before exec
    monkeypatch.setenv("UNRELATED_VAR", "keep-me")

    called = mocker.patch.object(
        claude_cli.subprocess,
        "run",
        return_value=_ok_subprocess('{"result": "claude says hi"}'),
    )

    result = claude_cli.run(
        "system-prompt-goes-here",
        [tiny_png],
        extras={"claude_alias": "sonnet"},
    )

    assert isinstance(result, EvalResult)
    assert result.content == "claude says hi"

    args, kwargs = called.call_args
    cmd = args[0]
    # Required flags, verbatim
    assert cmd[0] == "claude"
    assert cmd[1] == "-p"
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "sonnet"
    assert "--tools" in cmd and cmd[cmd.index("--tools") + 1] == "Read"
    assert "--setting-sources" in cmd and cmd[cmd.index("--setting-sources") + 1] == ""
    assert "--disable-slash-commands" in cmd
    assert "--no-session-persistence" in cmd
    assert "--dangerously-skip-permissions" in cmd
    assert "--system-prompt" in cmd
    assert cmd[cmd.index("--system-prompt") + 1] == "system-prompt-goes-here"
    assert "--output-format" in cmd and cmd[cmd.index("--output-format") + 1] == "json"

    # The user prompt (last arg) embeds the image path, not base64.
    user_prompt = cmd[-1]
    assert str(tiny_png.resolve()) in user_prompt

    # CLAUDECODE must be stripped from env; unrelated vars preserved.
    env = kwargs["env"]
    assert "CLAUDECODE" not in env
    assert env.get("UNRELATED_VAR") == "keep-me"


def test_run_falls_back_to_raw_stdout_when_not_json(tiny_png, mocker):
    mocker.patch.object(
        claude_cli.subprocess, "run", return_value=_ok_subprocess("raw text")
    )

    result = claude_cli.run("x", [tiny_png], extras={"claude_alias": "opus"})

    assert result.content == "raw text"


def test_run_raises_runtime_error_on_nonzero_returncode(tiny_png, mocker):
    mocker.patch.object(
        claude_cli.subprocess,
        "run",
        return_value=_ok_subprocess(stdout="", returncode=1),
    )

    with pytest.raises(RuntimeError) as exc_info:
        claude_cli.run("x", [tiny_png], extras={"claude_alias": "sonnet"})
    assert "claude CLI exited with code 1" in str(exc_info.value)


def test_credential_test_happy_path(mocker):
    mocker.patch.object(
        claude_cli.subprocess,
        "run",
        return_value=SimpleNamespace(returncode=0, stdout="claude 1.0", stderr=""),
    )

    result = claude_cli.credential_test({})
    assert isinstance(result, CredentialTestResult)
    assert result.ok is True


def test_credential_test_missing_binary_is_not_raised(mocker):
    mocker.patch.object(
        claude_cli.subprocess, "run", side_effect=FileNotFoundError()
    )

    result = claude_cli.credential_test({})

    assert result.ok is False
    assert "`claude` CLI not found on PATH" == result.reason


def test_credential_test_nonzero_exit_is_not_raised(mocker):
    err = subprocess.CalledProcessError(
        returncode=127, cmd=["claude", "--version"], stderr="boom"
    )
    mocker.patch.object(claude_cli.subprocess, "run", side_effect=err)

    result = claude_cli.credential_test({})

    assert result.ok is False
    assert "127" in (result.reason or "")


def test_shape_registration():
    shape = SHAPES["claude-cli"]
    assert shape.name == "claude-cli"
    assert shape.credential_fields == ()
    assert shape.requires_deployment_map is False
