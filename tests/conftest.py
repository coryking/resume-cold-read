"""Shared pytest fixtures for the cold_read test suite."""

from __future__ import annotations

import pytest

from cold_read import config as _config


_AZURE_VARS = (
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_MAAS_API_KEY",
    "AZURE_MAAS_ENDPOINT",
    "AZURE_PRIMARY_API_KEY",
    "AZURE_PRIMARY_ENDPOINT",
    "AZURE_SECONDARY_API_KEY",
    "AZURE_SECONDARY_ENDPOINT",
)


@pytest.fixture
def fake_dirs(monkeypatch, tmp_path):
    """Redirect platformdirs lookups into a tmpdir tree and chdir into it.

    Also drops Azure credential env vars so tests don't inherit whatever
    is in the dev shell. Returns `(config_dir, data_dir, cwd)` for tests
    that need to read files back.
    """
    cfg = tmp_path / "config"
    data = tmp_path / "data"
    monkeypatch.setattr(
        _config.platformdirs, "user_config_dir", lambda app_name: str(cfg)
    )
    monkeypatch.setattr(
        _config.platformdirs, "user_data_dir", lambda app_name: str(data)
    )
    monkeypatch.chdir(tmp_path)
    for var in _AZURE_VARS:
        monkeypatch.delenv(var, raising=False)
    return cfg, data, tmp_path
