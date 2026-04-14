"""`resume-cold-read init` — interactive first-run wizard.

Configures one provider at a time with a "configure another provider?"
loop. Each provider is only written after its credential test passes,
and the write is atomic (per-provider commit), so a Ctrl-C between
providers preserves everything already configured this session.

For `azure-openai`, the wizard queries `/openai/deployments` on the
given endpoint and filters to vision-capable model families via a
hardcoded prefix allow-list. On any HTTP failure the wizard silently
drops to free-form deployment entry — it does not attempt to diagnose
Azure configuration on the user's behalf.
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Optional

import httpx
from dotenv import dotenv_values
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from cold_read import config as _config
from cold_read import registry as _registry
from cold_read.providers import SHAPES, is_reserved
from cold_read.providers.shape import EnvField, ProviderShape

console = Console()

# Pinned so a future Azure API breaking change is a one-line bump and not a
# grep hunt.
LISTING_API_VERSION = "2024-12-01-preview"
LISTING_TIMEOUT = httpx.Timeout(5.0, read=15.0)

# Vision-capable GPT model families as exposed by Azure deployment
# metadata's `model` field. Extend as new families ship — the check is a
# startswith() match, so family prefixes cover all their point releases.
VISION_MODEL_PREFIXES: tuple[str, ...] = (
    "gpt-4o",
    "gpt-4.1",
    "gpt-5",
    "gpt-5.1",
    "gpt-5.2",
)

RECOMMENDED_FIRST_SHAPE = "azure-openai"


def init_command() -> None:
    """Run the init wizard from the CLI callback."""
    console.print(
        "\n[bold cyan]resume-cold-read init[/bold cyan]\n"
        "Configure one or more provider shapes. Credentials land in "
        f"`{_config.env_file()}` and non-secret state in "
        f"`{_config.config_file()}`.\n"
    )

    user_config = _config.read_config()
    initial_default = user_config.default_model
    env_values = _load_env_values()

    configured_shapes: list[str] = []

    while True:
        shape_name = _prompt_shape_choice(configured_shapes, user_config)
        if shape_name is None:
            break

        result = _configure_shape(shape_name, env_values, user_config)
        if result is not None:
            env_updates, provider_cfg = result
            env_values.update(env_updates)
            if provider_cfg is not None:
                user_config = replace(
                    user_config,
                    providers={**user_config.providers, shape_name: provider_cfg},
                )
            _write_env_file(env_values)
            _config.write_config(user_config)
            console.print(
                f"[green]Saved {shape_name} configuration.[/green]\n"
            )
            configured_shapes.append(shape_name)

        if not Confirm.ask("Configure another provider?", default=False):
            break

    # Pick default_model from aliases whose shape was either tested OK
    # this session or already has a provider entry from a prior session.
    user_config = _prompt_default_model(user_config, configured_shapes)
    # Persist only if something actually changed. Avoids creating an empty
    # config.toml on a run where the user configured nothing.
    if (
        user_config.default_model != initial_default
        or configured_shapes
        or user_config.providers
    ):
        _config.write_config(user_config)

    console.print(
        "\n[bold green]Done.[/bold green] Run `resume-cold-read doctor` to verify."
    )


# ---------------------------------------------------------------------- UI


def _prompt_shape_choice(
    configured: list[str], user_config: _config.Config
) -> Optional[str]:
    """Show available shapes and return the user's pick, or None to exit."""
    available = [name for name in SHAPES if not is_reserved(name)]
    table = Table(title="Available provider shapes")
    table.add_column("Shape", style="bold")
    table.add_column("Models that use it")
    table.add_column("Status")

    for name in available:
        aliases = _registry.aliases_for_shape(name)
        resolvable = sum(
            1 for a in aliases if _alias_resolvable(a, user_config)
        )
        status = _status_label(name, aliases, resolvable, configured)
        table.add_row(name, ", ".join(aliases) or "—", status)

    console.print(table)

    choice = Prompt.ask(
        "Which provider to configure? (blank to finish)",
        choices=[*available, ""],
        default=RECOMMENDED_FIRST_SHAPE if not configured else "",
        show_choices=False,
    )
    return choice if choice else None


def _status_label(
    name: str, aliases: list[str], resolvable: int, configured: list[str]
) -> str:
    if name in configured:
        return "[green]configured this session[/green]"
    if aliases and resolvable == len(aliases):
        return "[green]resolvable[/green]"
    if aliases and resolvable > 0:
        return f"[yellow]partial ({resolvable}/{len(aliases)})[/yellow]"
    return "[dim]not configured[/dim]"


def _prompt_default_model(
    user_config: _config.Config, tested_shapes: list[str]
) -> _config.Config:
    """Offer the user a default_model from the credential-tested alias set.

    An alias is eligible only when its shape was either (a) configured
    successfully this session or (b) already carries a provider entry
    from a prior session. This prevents offering, say, `claude-sonnet`
    as a default when the user hasn't actually verified the CLI is
    installed.
    """
    eligible_shapes = set(tested_shapes) | set(user_config.providers.keys())
    eligible = [
        alias
        for alias in _registry.list_aliases()
        if _registry.MODELS[alias].shape in eligible_shapes
        and _alias_resolvable(alias, user_config)
    ]
    if not eligible:
        console.print(
            "[yellow]No credential-tested aliases yet; skipping default_model.[/yellow]"
        )
        return user_config

    current = user_config.default_model
    default = current if current in eligible else eligible[0]
    choice = Prompt.ask(
        f"Default model? (current: {current or 'unset'})",
        choices=eligible,
        default=default,
    )
    return replace(user_config, default_model=choice)


# ----------------------------------------------------- per-shape workflows


def _configure_shape(
    shape_name: str,
    env_values: dict[str, str],
    user_config: _config.Config,
) -> Optional[tuple[dict[str, str], Optional[_config.ProviderConfig]]]:
    """Dispatch to the shape-specific configuration flow. Returns
    (env_updates, provider_config) if credentials verified, else None.

    Adding a new concrete shape requires a branch here. The final
    `raise` (instead of a silent `return None`) makes that requirement
    loud — `init` should never accept a shape it has no flow for.
    """
    shape = SHAPES[shape_name]

    if shape_name == "azure-openai":
        return _configure_azure_openai(shape, env_values)
    if shape_name == "azure-maas":
        return _configure_azure_maas(shape, env_values)
    if shape_name == "claude-cli":
        return _configure_claude_cli(shape)
    if is_reserved(shape_name):
        # Reserved shapes should have been filtered earlier.
        return None
    raise RuntimeError(
        f"No wizard flow for concrete shape {shape_name!r}. "
        f"Add a branch in wizard._configure_shape."
    )


def _configure_azure_openai(
    shape: ProviderShape, env_values: dict[str, str]
) -> Optional[tuple[dict[str, str], _config.ProviderConfig]]:
    """Prompt for Azure-OpenAI creds, list deployments, test, return config."""
    current_env = dict(env_values)
    while True:
        env_updates = _prompt_credentials(shape, current_env)
        _apply_env(env_updates)

        # Attempt deployments listing (graceful fallback on any failure).
        deployments = _try_list_vision_deployments(
            env_updates["AZURE_OPENAI_ENDPOINT"],
            env_updates["AZURE_OPENAI_API_KEY"],
        )

        aliases = _registry.aliases_for_shape("azure-openai")
        deployment_map: dict[str, str] = {}
        for alias in aliases:
            entry = _registry.MODELS[alias]
            api_version = entry.extras.get("api_version", LISTING_API_VERSION)
            deployment = _pick_deployment_for_alias(alias, deployments)
            if deployment is None:
                deployment = _prompt_nonempty(
                    f"Deployment name for `{alias}` "
                    f"(api-version {api_version})"
                )
            deployment_map[alias] = deployment

        # Credential test uses the first alias's api_version (they're all
        # the same family in practice; pick one deterministically).
        test_alias = next(iter(deployment_map))
        test_api_version = _registry.MODELS[test_alias].extras.get(
            "api_version", LISTING_API_VERSION
        )
        test_result = shape.credential_test({"api_version": test_api_version})
        if test_result.ok:
            return env_updates, _config.ProviderConfig(deployment_map=deployment_map)

        console.print(
            f"[red]Credential test failed:[/red] {test_result.reason}"
        )
        if not Confirm.ask("Re-enter credentials?", default=True):
            return None
        # On retry, the just-rejected values seed the next prompt, so the
        # user only has to fix the field that was wrong rather than re-type
        # everything.
        current_env = {**current_env, **env_updates}


def _configure_azure_maas(
    shape: ProviderShape, env_values: dict[str, str]
) -> Optional[tuple[dict[str, str], _config.ProviderConfig]]:
    """Prompt for MaaS creds + per-alias deployment, test, return config."""
    current_env = dict(env_values)
    while True:
        env_updates = _prompt_credentials(shape, current_env)
        _apply_env(env_updates)

        deployment_map: dict[str, str] = {}
        for alias in _registry.aliases_for_shape("azure-maas"):
            deployment_map[alias] = _prompt_nonempty(
                f"Deployment name for `{alias}` on this MaaS endpoint"
            )

        test_alias = next(iter(deployment_map))
        test_result = shape.credential_test(
            {"deployment": deployment_map[test_alias]}
        )
        if test_result.ok:
            return env_updates, _config.ProviderConfig(deployment_map=deployment_map)

        console.print(f"[red]Credential test failed:[/red] {test_result.reason}")
        if not Confirm.ask("Re-enter credentials?", default=True):
            return None
        current_env = {**current_env, **env_updates}


def _configure_claude_cli(
    shape: ProviderShape,
) -> Optional[tuple[dict[str, str], Optional[_config.ProviderConfig]]]:
    """No creds to prompt; just verify the CLI is installed."""
    test_result = shape.credential_test({})
    if test_result.ok:
        console.print(
            "[green]`claude` CLI detected.[/green] "
            "`claude-sonnet` and `claude-opus` aliases are ready."
        )
        return {}, None

    console.print(
        f"[yellow]claude-cli unavailable:[/yellow] {test_result.reason}\n"
        f"Install the Claude CLI and rerun init."
    )
    return None


# --------------------------------------------------------------- helpers


def _prompt_credentials(
    shape: ProviderShape, env_values: dict[str, str]
) -> dict[str, str]:
    """Prompt for every credential field the shape declares."""
    updates: dict[str, str] = {}
    for field in shape.credential_fields:
        existing = env_values.get(field.name) or ""
        if "ENDPOINT" in field.name or field.name.endswith("_URL"):
            updates[field.name] = _prompt_endpoint(field, existing)
        else:
            updates[field.name] = _prompt_secret_or_value(field, existing)
    return updates


def _prompt_endpoint(field: EnvField, existing: str) -> str:
    """Prompt for an endpoint URL, requiring https:// and stripping whitespace."""
    while True:
        prompt = f"{field.description} ({field.name})"
        value = Prompt.ask(prompt, default=existing or None)
        if value is None:
            continue
        value = value.strip()
        if _has_newline(value):
            console.print("[red]Value cannot contain a newline.[/red]")
            continue
        if not value.startswith("https://"):
            console.print(
                "[red]Endpoint must start with https://[/red] — got "
                f"{value!r}."
            )
            continue
        return value


def _prompt_secret_or_value(field: EnvField, existing: str) -> str:
    prompt = f"{field.description} ({field.name})"
    while True:
        value = Prompt.ask(
            prompt,
            password=field.secret,
            default=existing or None,
        )
        if value is None:
            continue
        value = value.strip()
        if not value:
            continue
        if _has_newline(value):
            console.print("[red]Value cannot contain a newline.[/red]")
            continue
        return value


def _prompt_nonempty(prompt: str) -> str:
    """Prompt for a non-empty single-line value (e.g. deployment names).

    Empty strings would silently land in `config.toml` / `.env`; a value
    containing `\\n` would corrupt either file. Both get re-prompted.
    """
    while True:
        value = Prompt.ask(prompt).strip()
        if not value:
            console.print("[red]Value cannot be empty.[/red]")
            continue
        if _has_newline(value):
            console.print("[red]Value cannot contain a newline.[/red]")
            continue
        return value


def _has_newline(value: str) -> bool:
    return "\n" in value or "\r" in value


def _try_list_vision_deployments(
    endpoint: str, api_key: str
) -> list[dict]:
    """Return vision-capable deployments from Azure, or [] on any failure."""
    url = f"{endpoint.rstrip('/')}/openai/deployments"
    try:
        with httpx.Client(timeout=LISTING_TIMEOUT) as client:
            response = client.get(
                url,
                params={"api-version": LISTING_API_VERSION},
                headers={"api-key": api_key},
            )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:  # noqa: BLE001 — every failure falls back identically
        console.print(
            f"[dim]Could not list deployments ({type(exc).__name__}); "
            f"falling back to manual entry.[/dim]"
        )
        return []

    items = data.get("data") or []
    return [d for d in items if _is_vision_family(d.get("model"))]


def _is_vision_family(model_name: Optional[str]) -> bool:
    if not model_name:
        return False
    return any(model_name.startswith(p) for p in VISION_MODEL_PREFIXES)


def _pick_deployment_for_alias(
    alias: str, deployments: list[dict]
) -> Optional[str]:
    """Present a pick-list of deployments for `alias`, or None to fall back."""
    if not deployments:
        return None

    table = Table(title=f"Vision-capable deployments for `{alias}`")
    table.add_column("#", style="cyan")
    table.add_column("Deployment")
    table.add_column("Model")
    for i, d in enumerate(deployments, start=1):
        table.add_row(str(i), d.get("id", "?"), d.get("model", "?"))
    console.print(table)

    choice = Prompt.ask(
        f"Pick deployment for `{alias}` (number, or blank for manual entry)",
        default="",
    )
    if not choice:
        return None
    try:
        index = int(choice) - 1
    except ValueError:
        return None
    if 0 <= index < len(deployments):
        return deployments[index].get("id")
    return None


def _alias_resolvable(alias: str, user_config: _config.Config) -> bool:
    try:
        _registry.resolve(alias, user_config)
    except _registry.UnresolvedDeploymentError:
        return False
    except _registry.UnknownModelError:
        return False
    return True


def _apply_env(updates: dict[str, str]) -> None:
    """Apply env-var updates to the live process so credential_test() sees them."""
    for k, v in updates.items():
        os.environ[k] = v


def _load_env_values() -> dict[str, str]:
    """Read the current config-dir .env as a plain dict, or {} if absent."""
    path = _config.env_file()
    if not path.is_file():
        return {}
    loaded = dotenv_values(path)
    return {k: v for k, v in loaded.items() if v is not None}


def _write_env_file(env_values: dict[str, str]) -> None:
    """Atomically write the merged .env at mode 0o600."""
    _config.write_env_file(env_values)


__all__ = ["init_command"]
