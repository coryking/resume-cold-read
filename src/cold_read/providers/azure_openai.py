"""`azure-openai` provider shape — calibrated default for GPT-class models."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from openai import AzureOpenAI

from cold_read.providers._encoding import build_chat_messages
from cold_read.providers.shape import (
    CredentialTestResult,
    CredentialsMissingError,
    EnvField,
    EvalResult,
    ProviderShape,
)

CREDENTIAL_FIELDS = (
    EnvField("AZURE_OPENAI_API_KEY", "Azure OpenAI API key", secret=True),
    EnvField(
        "AZURE_OPENAI_ENDPOINT",
        "Azure OpenAI resource endpoint (https://<name>.openai.azure.com/)",
    ),
)

# Tight timeout for `credential_test()` and other quick health checks.
# Real eval calls go through `run()` and use the SDK default — a slow
# model thinking shouldn't be confused with a credential probe hanging.
_CREDENTIAL_TEST_TIMEOUT = httpx.Timeout(5.0, read=15.0)


def _build_client(api_version: str, *, timeout: httpx.Timeout | None = None) -> AzureOpenAI:
    missing = SHAPE.missing_env()
    if missing:
        raise CredentialsMissingError(
            f"Missing env vars for azure-openai: {', '.join(missing)}"
        )
    kwargs: dict = {
        "azure_endpoint": os.environ["AZURE_OPENAI_ENDPOINT"],
        "api_key": os.environ["AZURE_OPENAI_API_KEY"],
        "api_version": api_version,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return AzureOpenAI(**kwargs)


def run(prompt_text: str, images: list[Path], extras: dict) -> EvalResult:
    """Send a chat-completions request against the configured deployment.

    Required extras:
      - `deployment` (str): Azure deployment name to invoke.
      - `api_version` (str): API version the deployment expects.
      - `reasoning` (bool, optional): if True, add `reasoning_effort="high"`.
      - `max_images` (int | None, optional): cap image count.
    """
    deployment = extras["deployment"]
    api_version = extras["api_version"]
    client = _build_client(api_version)
    messages = build_chat_messages(prompt_text, images, extras.get("max_images"))

    params: dict = {"max_completion_tokens": 16384}
    if extras.get("reasoning"):
        params["reasoning_effort"] = "high"

    response = client.chat.completions.create(
        model=deployment,
        messages=messages,
        **params,
    )

    choice = response.choices[0]
    usage = response.usage
    return EvalResult(
        content=choice.message.content or "",
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
    )


def credential_test(extras: dict) -> CredentialTestResult:
    """Cheap `models.list()` round-trip; any 2xx means creds resolved.

    Uses a tight timeout so a misconfigured endpoint surfaces in
    seconds, not the SDK's 10-minute default.
    """
    api_version = extras.get("api_version", "2024-12-01-preview")
    try:
        client = _build_client(api_version, timeout=_CREDENTIAL_TEST_TIMEOUT)
        client.models.list()
    except CredentialsMissingError as exc:
        return CredentialTestResult(ok=False, reason=str(exc))
    except Exception as exc:  # noqa: BLE001 — any upstream failure is a negative result
        return CredentialTestResult(
            ok=False, reason=f"{type(exc).__name__}: {exc}"
        )
    return CredentialTestResult(ok=True)


SHAPE = ProviderShape(
    name="azure-openai",
    credential_fields=CREDENTIAL_FIELDS,
    requires_deployment_map=True,
    run=run,
    credential_test=credential_test,
)
