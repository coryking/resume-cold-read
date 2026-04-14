"""`resume-cold-read doctor` — four-section diagnostic checklist.

Reports on Install, Config, Providers, and Models. Each check produces
a green / yellow / red status. Exits 0 iff every Install check is green
AND at least one Model resolves green; all other states exit 1.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Optional

import typer
from rich.console import Console

from cold_read import config as _config
from cold_read import prompts as _prompts
from cold_read import registry as _registry
from cold_read.providers import SHAPES, is_reserved

console = Console()

GREEN = "green"
YELLOW = "yellow"
RED = "red"

_GLYPH = {
    GREEN: "[green]●[/green]",
    YELLOW: "[yellow]⚠[/yellow]",
    RED: "[red]✗[/red]",
}


@dataclass(frozen=True)
class Check:
    status: str
    message: str


def doctor_command() -> None:
    user_config = _config.read_config()

    install = _check_install()
    config = _check_config()
    provider_results, provider_checks = _check_providers(user_config)
    models = _check_models(user_config, provider_results)

    _render("Install", install)
    _render("Config", config)
    _render("Providers", provider_checks)
    _render("Models", models)

    raise typer.Exit(_compute_exit_code(install, models))


# -- Section: Install -----------------------------------------------------


def _check_install() -> list[Check]:
    checks: list[Check] = []
    try:
        manifest = _prompts.load_manifest()
        n = len(manifest.get("phases", []))
        checks.append(Check(GREEN, f"packaged resources readable ({n} phases)"))
    except Exception as exc:  # noqa: BLE001
        checks.append(
            Check(
                RED,
                f"packaged resources unreadable ({type(exc).__name__}: {exc}). "
                f"Try `uv tool install --force resume-cold-read`.",
            )
        )

    pdftoppm_path = shutil.which("pdftoppm")
    if pdftoppm_path:
        checks.append(Check(GREEN, f"`pdftoppm` at {pdftoppm_path}"))
    else:
        checks.append(
            Check(
                RED,
                "`pdftoppm` not on PATH. Install poppler "
                "(`brew install poppler` / `apt install poppler-utils`).",
            )
        )

    return checks


# -- Section: Config ------------------------------------------------------


_DEPRECATED_PREFIXES = ("AZURE_PRIMARY_", "AZURE_SECONDARY_")


def _check_config() -> list[Check]:
    checks: list[Check] = []

    cfg_dir = _config.config_dir()
    checks.append(Check(GREEN, f"config dir at {cfg_dir}"))

    env_path = _config.env_file()
    if env_path.is_file():
        checks.append(Check(GREEN, f".env present at {env_path}"))
    else:
        checks.append(
            Check(
                YELLOW,
                f".env not found at {env_path}. Run `resume-cold-read init`.",
            )
        )

    cfg_path = _config.config_file()
    if cfg_path.is_file():
        checks.append(Check(GREEN, f"config.toml present at {cfg_path}"))
    else:
        checks.append(
            Check(
                YELLOW,
                f"config.toml not found at {cfg_path}. Run `resume-cold-read init`.",
            )
        )

    deprecated = sorted(
        k
        for k in os.environ
        if any(k.startswith(p) for p in _DEPRECATED_PREFIXES)
    )
    if deprecated:
        checks.append(
            Check(
                YELLOW,
                f"Deprecated env vars set: {', '.join(deprecated)}. "
                f"Rename to AZURE_OPENAI_* / AZURE_MAAS_*; the old names are ignored.",
            )
        )

    return checks


# -- Section: Providers ---------------------------------------------------


def _check_providers(
    user_config: _config.Config,
) -> tuple[dict[str, Optional[bool]], list[Check]]:
    """Run credential_test per concrete shape whose env fields are present.

    Returns a pair: `(results, checks)`. `results[shape_name]` is True when
    the shape tested OK, False when it failed, and None when its env
    fields are not all set (so no test was run).
    """
    results: dict[str, Optional[bool]] = {}
    checks: list[Check] = []

    for shape_name, shape in SHAPES.items():
        if is_reserved(shape_name):
            continue

        missing = [
            f.name for f in shape.credential_fields if not os.environ.get(f.name)
        ]
        if missing:
            results[shape_name] = None
            checks.append(
                Check(
                    YELLOW,
                    f"{shape_name}: not configured (missing {', '.join(missing)}). "
                    f"Run `resume-cold-read init`.",
                )
            )
            continue

        extras = _probe_extras_for(shape_name, user_config)
        test = shape.credential_test(extras)
        if test.ok:
            results[shape_name] = True
            checks.append(Check(GREEN, f"{shape_name}: credentials verified"))
        else:
            results[shape_name] = False
            checks.append(Check(RED, f"{shape_name}: {test.reason}"))

    return results, checks


def _probe_extras_for(
    shape_name: str, user_config: _config.Config
) -> dict:
    """Pick sensible defaults for a shape's `credential_test()` call."""
    if shape_name == "azure-openai":
        # Pick any alias's api_version on this shape. All gpt families today
        # share one.
        for alias, entry in _registry.MODELS.items():
            if entry.shape == shape_name:
                return {
                    "api_version": entry.extras.get(
                        "api_version", "2024-12-01-preview"
                    )
                }
        return {"api_version": "2024-12-01-preview"}
    if shape_name == "azure-maas":
        # Use the first deployment the user has mapped for this shape.
        provider_cfg = user_config.providers.get(shape_name)
        if provider_cfg and provider_cfg.deployment_map:
            first_alias = next(iter(provider_cfg.deployment_map))
            return {"deployment": provider_cfg.deployment_map[first_alias]}
        return {}
    return {}


# -- Section: Models ------------------------------------------------------


def _check_models(
    user_config: _config.Config,
    provider_results: dict[str, Optional[bool]],
) -> list[Check]:
    checks: list[Check] = []
    default = user_config.default_model

    for alias in _registry.list_aliases():
        marker = " [bold](default)[/bold]" if alias == default else ""
        entry = _registry.MODELS[alias]
        try:
            _registry.resolve(alias, user_config)
        except _registry.UnresolvedDeploymentError:
            checks.append(
                Check(
                    YELLOW,
                    f"{alias}{marker}: deployment not configured on {entry.shape}. "
                    f"Run `resume-cold-read init`.",
                )
            )
            continue

        shape_ok = provider_results.get(entry.shape)
        if shape_ok is True:
            checks.append(Check(GREEN, f"{alias}{marker}: usable"))
        elif shape_ok is False:
            checks.append(
                Check(RED, f"{alias}{marker}: {entry.shape} shape unhealthy")
            )
        else:
            checks.append(
                Check(
                    YELLOW,
                    f"{alias}{marker}: {entry.shape} shape not configured",
                )
            )
    return checks


# -- Rendering + exit code -----------------------------------------------


def _render(title: str, checks: list[Check]) -> None:
    console.print(f"\n[bold]{title}[/bold]")
    for check in checks:
        glyph = _GLYPH[check.status]
        console.print(f"  {glyph} {check.message}")


def _compute_exit_code(install: list[Check], models: list[Check]) -> int:
    """0 iff Install is all green AND at least one Model is green.

    Yellow alone never triggers a non-zero exit.
    """
    if any(c.status == RED for c in install):
        return 1
    if not any(c.status == GREEN for c in models):
        return 1
    return 0


__all__ = ["doctor_command"]
