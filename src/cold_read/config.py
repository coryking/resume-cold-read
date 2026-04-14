"""Bucket-2 user-owned persistent config.

Exposes:
- `config_dir()` / `data_dir()`: platformdirs paths, created on first access.
- `load_env()`: layered `.env` load (config dir → CWD → process env, with
  process env always winning).
- `read_config()` / `write_config()`: `config.toml` serialization of
  `default_model` and per-provider `deployment_map`s.
- `resolve_company()`: slug-or-path resolution rooted in the config dir.
  **Never** falls back to bucket-1 packaged prompts. The slug branch is
  guarded against path-traversal.

Everything here is the authoritative loader for bucket-2 state. Callers
should not cons up `~/.config/...` paths by hand.
"""

from __future__ import annotations

import os
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs
from dotenv import load_dotenv

APP_NAME = "resume-cold-read"

_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# Providers we know how to round-trip in config.toml. Keeping the list
# explicit means an unknown section in a hand-edited config.toml falls
# through to "ignored" rather than silently shaping into a ProviderConfig
# with surprising defaults.
_KNOWN_PROVIDERS = ("azure-openai", "azure-maas", "claude-cli", "openai", "anthropic")


@dataclass
class ProviderConfig:
    """Per-provider config block. Currently just a deployment map, but shaped
    so shape-specific fields can join later without moving the read/write
    machinery."""

    deployment_map: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    """In-memory projection of config.toml."""

    default_model: str | None = None
    providers: dict[str, ProviderConfig] = field(default_factory=dict)


def config_dir() -> Path:
    """Return the user config directory, creating it with 0o700 if absent."""
    path = Path(platformdirs.user_config_dir(APP_NAME))
    if not path.exists():
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    # mkdir's `mode` is masked by umask; the explicit chmod is the
    # authoritative step that guarantees 0o700 regardless of umask.
    os.chmod(path, 0o700)
    return path


def data_dir() -> Path:
    """Return the user data directory, creating it if absent."""
    path = Path(platformdirs.user_data_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    return config_dir() / "config.toml"


def env_file() -> Path:
    return config_dir() / ".env"


def companies_dir() -> Path:
    return config_dir() / "companies"


def load_env() -> None:
    """Layer .env files into the process environment.

    Order (highest precedence last-read-wins semantics, but every call uses
    `override=False`):

    1. Config dir `.env` — loaded first, so it sets vars that are not
       already in the process env.
    2. CWD `.env` — loaded second; `override=False` means it does not
       clobber what step 1 (or the process env) already provided.
    3. Process env — always wins because `override=False` is used on both
       file loads.

    Rationale: a user's `~/.config/resume-cold-read/.env` is the documented
    home for credentials, but a developer working on the code can still
    override with a shell-exported variable. The CWD `.env` is a
    convenience for folks who run from a checkout.
    """
    cfg = env_file()
    if cfg.is_file():
        load_dotenv(cfg, override=False)
    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file() and cwd_env.resolve() != cfg.resolve():
        load_dotenv(cwd_env, override=False)


def read_config() -> Config:
    """Parse config.toml, or return an empty Config if absent."""
    path = config_file()
    if not path.is_file():
        return Config()

    data = tomllib.loads(path.read_text())
    default_model = data.get("default_model")

    providers: dict[str, ProviderConfig] = {}
    raw_providers = data.get("providers", {}) or {}
    for name, block in raw_providers.items():
        if name not in _KNOWN_PROVIDERS:
            continue
        if not isinstance(block, dict):
            continue
        deployment_map = block.get("deployment_map", {}) or {}
        if not isinstance(deployment_map, dict):
            deployment_map = {}
        providers[name] = ProviderConfig(deployment_map=dict(deployment_map))

    return Config(default_model=default_model, providers=providers)


def write_config(cfg: Config) -> Path:
    """Atomically write a Config to `config.toml` (mode 0o600)."""
    return _atomic_write(config_file(), _serialize_config(cfg), mode=0o600)


def resolve_company(slug_or_path: str) -> Path | None:
    """Return the file path for a company dossier, or None if unresolvable.

    Resolution order:
    1. If the input is an existing file on disk, return it as-is.
    2. Otherwise, treat as a slug, validate against `[a-z0-9][a-z0-9_-]*`,
       and join into `config_dir()/companies/{slug}.md`. Confirm the
       resolved path is still under `companies/` before returning.

    Never falls back to bucket-1 packaged prompts. A malformed slug
    returns None — the caller is expected to warn and carry on.
    """
    candidate = Path(slug_or_path)
    if candidate.is_file():
        return candidate

    if not _SLUG_PATTERN.match(slug_or_path):
        return None

    base = companies_dir().resolve()
    target = (base / f"{slug_or_path}.md").resolve()
    if not target.is_relative_to(base):
        return None
    return target if target.is_file() else None


# -- Internals -------------------------------------------------------------


def _atomic_write(path: Path, content: str, mode: int = 0o600) -> Path:
    """Write `content` to `path` via tempfile-in-same-dir + os.replace.

    Guarantees that a crash or Ctrl-C mid-write leaves the pre-existing
    file intact and that the final file lands at `mode` regardless of
    umask.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return path


def _serialize_config(cfg: Config) -> str:
    """Render a Config as minimal TOML.

    Hand-rolled writer instead of a `tomli-w` dependency. Schema is small
    and flat: a top-level `default_model` and one `[providers.<name>]`
    table per configured provider, each with a `deployment_map` inline
    table.
    """
    lines: list[str] = []
    if cfg.default_model is not None:
        lines.append(f'default_model = "{_escape(cfg.default_model)}"')
        lines.append("")

    for name in _KNOWN_PROVIDERS:
        provider = cfg.providers.get(name)
        if provider is None:
            continue
        if not provider.deployment_map:
            continue
        lines.append(f'[providers."{name}"]')
        inline_items = ", ".join(
            f'"{_escape(alias)}" = "{_escape(dep)}"'
            for alias, dep in sorted(provider.deployment_map.items())
        )
        lines.append(f"deployment_map = {{ {inline_items} }}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')
