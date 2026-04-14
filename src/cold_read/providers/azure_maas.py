"""`azure-maas` provider shape — Models-as-a-Service endpoints (Grok, Llama, …)."""

from __future__ import annotations

import os
from pathlib import Path

from openai import OpenAI

from cold_read.providers._encoding import build_chat_messages
from cold_read.providers.shape import (
    CredentialTestResult,
    CredentialsMissingError,
    EnvField,
    EvalResult,
    ProviderShape,
)

CREDENTIAL_FIELDS = (
    EnvField("AZURE_MAAS_API_KEY", "Azure MaaS API key", secret=True),
    EnvField(
        "AZURE_MAAS_ENDPOINT",
        "Azure MaaS endpoint (e.g. https://<name>.services.ai.azure.com)",
    ),
)


def _build_client() -> OpenAI:
    missing = SHAPE.missing_env()
    if missing:
        raise CredentialsMissingError(
            f"Missing env vars for azure-maas: {', '.join(missing)}"
        )
    base_url = os.environ["AZURE_MAAS_ENDPOINT"].rstrip("/") + "/openai/v1/"
    return OpenAI(base_url=base_url, api_key=os.environ["AZURE_MAAS_API_KEY"])


def run(prompt_text: str, images: list[Path], extras: dict) -> EvalResult:
    """Chat-completions call through the MaaS `/openai/v1/` suffix.

    Required extras:
      - `deployment` (str): the MaaS deployment name.
      - `max_images` (int | None, optional): cap image count.
    """
    deployment = extras["deployment"]
    client = _build_client()
    messages = build_chat_messages(prompt_text, images, extras.get("max_images"))

    response = client.chat.completions.create(
        model=deployment,
        messages=messages,
        max_tokens=16384,
    )

    choice = response.choices[0]
    usage = response.usage
    return EvalResult(
        content=choice.message.content or "",
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
    )


def credential_test(extras: dict) -> CredentialTestResult:
    """Single-token echo completion against the configured deployment.

    The MaaS endpoint does not reliably expose `/v1/models`, so
    `models.list()` is not a safe probe here.
    """
    deployment = extras.get("deployment")
    if not deployment:
        return CredentialTestResult(
            ok=False, reason="No deployment configured; run init or edit config.toml"
        )
    try:
        client = _build_client()
        client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": "ok"}],
            max_tokens=1,
        )
    except CredentialsMissingError as exc:
        return CredentialTestResult(ok=False, reason=str(exc))
    except Exception as exc:  # noqa: BLE001
        return CredentialTestResult(
            ok=False, reason=f"{type(exc).__name__}: {exc}"
        )
    return CredentialTestResult(ok=True)


SHAPE = ProviderShape(
    name="azure-maas",
    credential_fields=CREDENTIAL_FIELDS,
    requires_deployment_map=True,
    run=run,
    credential_test=credential_test,
)
