"""Tests for the bucket-1 packaged-resource loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from cold_read import prompts


def test_load_manifest_returns_phases_dict():
    manifest = prompts.load_manifest()

    assert isinstance(manifest, dict)
    assert "phases" in manifest
    assert isinstance(manifest["phases"], list)
    assert len(manifest["phases"]) > 0


def test_load_prompt_known_phase_returns_non_empty():
    text = prompts.load_prompt("phase1-visual")

    assert isinstance(text, str)
    assert text.strip() != ""


def test_load_prompt_file_reads_preamble():
    text = prompts.load_prompt_file("preamble.md")

    assert isinstance(text, str)
    assert text.strip() != ""


def test_load_prompt_unknown_phase_raises_clear_error():
    with pytest.raises(prompts.UnknownPromptError) as exc_info:
        prompts.load_prompt("does-not-exist")

    msg = str(exc_info.value)
    assert "does-not-exist" in msg
    # Must enumerate available ids so the user knows what to pick
    assert "phase1-visual" in msg


def test_get_fixed_images_calibration_returns_two_readable_pngs():
    images = prompts.get_fixed_images("calibration")

    assert images is not None
    assert len(images) == 2
    for p in images:
        assert isinstance(p, Path)
        assert p.exists()
        # Basic PNG magic-number sniff; proves the bytes made it through
        # whatever copy importlib.resources chose to do.
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_get_fixed_images_pdf_phase_returns_none():
    assert prompts.get_fixed_images("phase1-visual") is None


def test_get_all_prompt_ids_excludes_calibration_and_composable():
    ids = prompts.get_all_prompt_ids()

    assert "calibration" not in ids
    assert "jd-eval" not in ids  # composable
    # At least the standalone phases remain
    assert "phase1-visual" in ids
