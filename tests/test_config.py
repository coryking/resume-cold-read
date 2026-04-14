"""Tests for the bucket-2 user-config loader."""

from __future__ import annotations

import os

import pytest

from cold_read import config as _config
from cold_read.config import (
    Config,
    ProviderConfig,
    load_env,
    read_config,
    resolve_company,
    write_config,
)


# -- config dir / data dir creation ----------------------------------------


def test_config_dir_is_created_with_0700(fake_dirs):
    cfg_root, _, _ = fake_dirs
    assert not cfg_root.exists()

    path = _config.config_dir()

    assert path == cfg_root
    assert path.is_dir()
    # Permission bits, last 3 octal digits
    assert oct(path.stat().st_mode)[-3:] == "700"


def test_data_dir_is_created_when_absent(fake_dirs):
    _, data_root, _ = fake_dirs
    assert not data_root.exists()

    path = _config.data_dir()

    assert path == data_root
    assert path.is_dir()


# -- config.toml round-trip ------------------------------------------------


def test_write_then_read_roundtrips_default_model_and_providers(fake_dirs):
    cfg_root, _, _ = fake_dirs
    cfg = Config(
        default_model="gpt52",
        providers={
            "azure-openai": ProviderConfig(deployment_map={"gpt52": "gpt-52-chat"}),
            "azure-maas": ProviderConfig(
                deployment_map={"grok4": "grok-4-fast-reasoning"}
            ),
        },
    )

    write_config(cfg)
    loaded = read_config()

    assert loaded.default_model == "gpt52"
    assert loaded.providers["azure-openai"].deployment_map == {"gpt52": "gpt-52-chat"}
    assert loaded.providers["azure-maas"].deployment_map == {
        "grok4": "grok-4-fast-reasoning"
    }


def test_write_sets_config_toml_to_0600(fake_dirs):
    write_config(Config(default_model="gpt52"))
    assert oct(_config.config_file().stat().st_mode)[-3:] == "600"


def test_read_config_returns_empty_when_file_absent(fake_dirs):
    loaded = read_config()
    assert loaded.default_model is None
    assert loaded.providers == {}


def test_write_then_read_drops_unknown_provider_sections(fake_dirs):
    # Hand-written config with an unknown provider stanza
    cfg_file = _config.config_file()
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text(
        'default_model = "gpt52"\n'
        "\n"
        '[providers."azure-openai"]\n'
        'deployment_map = { gpt52 = "gpt-52-chat" }\n'
        "\n"
        '[providers."fictional-provider"]\n'
        'deployment_map = { foo = "bar" }\n'
    )

    loaded = read_config()
    assert loaded.default_model == "gpt52"
    assert "fictional-provider" not in loaded.providers
    assert loaded.providers["azure-openai"].deployment_map == {"gpt52": "gpt-52-chat"}


# -- .env layering ---------------------------------------------------------


def test_load_env_sets_from_config_dir(fake_dirs, monkeypatch):
    cfg_root, _, _ = fake_dirs
    monkeypatch.delenv("RCR_TEST_VAR", raising=False)

    _config.config_dir()  # ensure dir exists
    (cfg_root / ".env").write_text("RCR_TEST_VAR=from_config_dir\n")

    load_env()

    assert os.environ.get("RCR_TEST_VAR") == "from_config_dir"


def test_load_env_config_dir_wins_over_cwd_when_both_set(
    fake_dirs, monkeypatch
):
    cfg_root, _, cwd = fake_dirs
    monkeypatch.delenv("RCR_TEST_VAR", raising=False)

    _config.config_dir()
    (cfg_root / ".env").write_text("RCR_TEST_VAR=from_config_dir\n")
    (cwd / ".env").write_text("RCR_TEST_VAR=from_cwd\n")

    load_env()

    assert os.environ.get("RCR_TEST_VAR") == "from_config_dir"


def test_load_env_process_env_wins_over_file_layers(fake_dirs, monkeypatch):
    cfg_root, _, _ = fake_dirs
    monkeypatch.setenv("RCR_TEST_VAR", "from_process")

    _config.config_dir()
    (cfg_root / ".env").write_text("RCR_TEST_VAR=from_config_dir\n")

    load_env()

    assert os.environ.get("RCR_TEST_VAR") == "from_process"


def test_load_env_noop_when_no_files_exist(fake_dirs, monkeypatch):
    monkeypatch.delenv("RCR_TEST_VAR", raising=False)
    # Don't create config dir or CWD .env
    load_env()
    assert "RCR_TEST_VAR" not in os.environ


# -- resolve_company -------------------------------------------------------


def test_resolve_company_returns_explicit_file_path(fake_dirs, tmp_path):
    dossier = tmp_path / "elsewhere" / "meridian.md"
    dossier.parent.mkdir(parents=True)
    dossier.write_text("# Meridian")

    result = resolve_company(str(dossier))
    assert result == dossier


def test_resolve_company_returns_slug_path_in_config_dir(fake_dirs):
    cfg_root, _, _ = fake_dirs
    comp_dir = _config.companies_dir()
    comp_dir.mkdir(parents=True)
    (comp_dir / "meridian-ai.md").write_text("# Meridian AI")

    result = resolve_company("meridian-ai")

    assert result is not None
    assert result.name == "meridian-ai.md"
    assert result.is_file()


def test_resolve_company_returns_none_when_slug_missing(fake_dirs):
    assert resolve_company("no-such-slug") is None


def test_resolve_company_does_not_fall_back_to_bucket_1(fake_dirs):
    # Even if we cons up the exact filename the old bucket-1 fallback used,
    # resolve_company must not find it in the packaged prompts.
    assert resolve_company("meridian-ai") is None


def test_resolve_company_rejects_path_traversal_slug(fake_dirs):
    # Reject anything that isn't a clean slug.
    assert resolve_company("../etc/passwd") is None
    assert resolve_company("a/b") is None
    assert resolve_company(".hidden") is None
    assert resolve_company("UPPER") is None
    assert resolve_company("") is None
