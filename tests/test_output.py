"""Tests for output-path resolution + save_individual."""

from __future__ import annotations

import re

import pytest

from cold_read import config as _config
from cold_read import output as _output


def test_default_output_path_lives_under_data_runs_dir(fake_dirs):
    _, data, _ = fake_dirs

    path = _output.default_output_path("my-resume")

    assert path.parent == data / "runs"
    assert path.suffix == ".md"


def test_default_output_path_has_dated_prefix_and_six_hex_suffix(fake_dirs):
    path = _output.default_output_path("my-resume")

    assert re.match(
        r"^\d{4}-\d{2}-\d{2}-my-resume-[0-9a-f]{6}\.md$",
        path.name,
    ), path.name


def test_default_output_path_honors_json_extension(fake_dirs):
    path = _output.default_output_path("my-resume", ext=".json")
    assert path.suffix == ".json"


def test_default_output_path_two_calls_produce_distinct_names(fake_dirs):
    a = _output.default_output_path("my-resume")
    b = _output.default_output_path("my-resume")
    assert a != b


def test_save_individual_writes_under_runs_dir_with_header(fake_dirs):
    _, data, _ = fake_dirs

    path = _output.save_individual(
        model_name="gpt52",
        deployment="gpt-52-chat",
        prompt_id="phase1-visual",
        content="hello world",
        pdf_name="resume.pdf",
    )

    assert path.parent == data / "runs"
    body = path.read_text()
    assert body.endswith("hello world")
    assert "# Eval: gpt52 / phase1-visual" in body
    assert "gpt-52-chat" in body
    assert "resume.pdf" in body


def test_save_individual_does_not_recreate_legacy_cold_read_output_dir(fake_dirs):
    _, _, cwd = fake_dirs

    _output.save_individual(
        model_name="gpt52",
        deployment="gpt-52-chat",
        prompt_id="phase1-visual",
        content="x",
        pdf_name="r.pdf",
    )

    # The old default wrote to a CWD-relative `cold-read-output/`. Nothing
    # in the new code should create that directory.
    assert not (cwd / "cold-read-output").exists()
