"""`claude-cli` provider shape — runs the installed `claude` CLI as a subprocess.

Preserves the exact flag set the inline implementation used: isolated
session, no slash commands, no setting sources, unrestricted Read tool,
and the `CLAUDECODE` env var stripped so nested invocations work.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from cold_read.providers.shape import (
    CredentialTestResult,
    EvalResult,
    ProviderShape,
)

CLAUDE_CLI_TIMEOUT_S = 300


def _env_without_claudecode() -> dict[str, str]:
    """Strip the marker that makes nested `claude` invocations refuse to run."""
    return {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}


def run(prompt_text: str, images: list[Path], extras: dict) -> EvalResult:
    """Invoke the `claude` CLI in isolated mode and return its result field.

    Images are passed as filesystem paths embedded in the user prompt;
    the CLI uses the Read tool to pull them off disk. This is the only
    shape where images are not base64-encoded.

    Required extras:
      - `claude_alias` (str): "sonnet" | "opus" | any CLI-accepted alias.
    """
    claude_alias = extras["claude_alias"]
    image_instructions = "\n".join(
        f"- Page {i + 1}: {png.resolve()}" for i, png in enumerate(images)
    )
    user_prompt = (
        "Read each of the following resume page images using the Read tool, "
        "then follow the evaluation instructions in your system prompt.\n\n"
        f"{image_instructions}"
    )

    cmd = [
        "claude",
        "-p",
        "--model", claude_alias,
        "--tools", "Read",
        "--setting-sources", "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--dangerously-skip-permissions",
        "--system-prompt", prompt_text,
        "--output-format", "json",
        user_prompt,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=tempfile.gettempdir(),
        env=_env_without_claudecode(),
        timeout=CLAUDE_CLI_TIMEOUT_S,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude CLI exited with code {result.returncode}: {result.stderr.strip()}"
        )

    try:
        parsed = json.loads(result.stdout)
        content = parsed.get("result", result.stdout)
    except json.JSONDecodeError:
        content = result.stdout.strip()

    # The CLI path does not surface token accounting.
    return EvalResult(content=content, prompt_tokens=0, completion_tokens=0)


def credential_test(extras: dict) -> CredentialTestResult:
    """Verify the `claude` CLI is on PATH. `--version` is fast and offline."""
    try:
        subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            env=_env_without_claudecode(),
            check=True,
        )
    except FileNotFoundError:
        return CredentialTestResult(ok=False, reason="`claude` CLI not found on PATH")
    except subprocess.TimeoutExpired:
        return CredentialTestResult(
            ok=False, reason="`claude --version` timed out"
        )
    except subprocess.CalledProcessError as exc:
        return CredentialTestResult(
            ok=False,
            reason=f"`claude --version` exited {exc.returncode}: {exc.stderr.strip()}",
        )
    return CredentialTestResult(ok=True)


SHAPE = ProviderShape(
    name="claude-cli",
    credential_fields=(),
    requires_deployment_map=False,
    run=run,
    credential_test=credential_test,
)
