"""Tests for `resume-cold-read eval --explain`."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cold_read import config as _config
from cold_read.cli import app

runner = CliRunner()


def _no_shape_run(monkeypatch):
    """Assert the explain path doesn't call any provider shape."""
    from cold_read.providers import SHAPES

    def boom(*args, **kwargs):
        raise AssertionError(
            "--explain must not invoke any provider shape's run()"
        )

    for name in SHAPES:
        # Can't patch the frozen dataclass field; swap the whole shape
        # with one whose run raises if ever called.
        from cold_read.providers.shape import ProviderShape
        orig = SHAPES[name]
        monkeypatch.setitem(
            SHAPES,
            name,
            ProviderShape(
                name=orig.name,
                credential_fields=orig.credential_fields,
                requires_deployment_map=orig.requires_deployment_map,
                run=boom,
                credential_test=orig.credential_test,
            ),
        )


def test_explain_manifest_mode_prints_phase_source(fake_dirs, monkeypatch):
    _no_shape_run(monkeypatch)

    result = runner.invoke(
        app, ["eval", "--prompt", "phase1-visual", "--explain"]
    )

    assert result.exit_code == 0, result.output
    assert "phase: phase1-visual" in result.output
    assert "[from: phase1-visual.md]" in result.output


def test_explain_calibration_shows_fixed_images(fake_dirs, monkeypatch):
    _no_shape_run(monkeypatch)

    result = runner.invoke(
        app, ["eval", "--prompt", "calibration", "--explain"]
    )

    assert result.exit_code == 0, result.output
    assert "[fixed images:" in result.output
    assert "page-1.png" in result.output
    assert "page-2.png" in result.output


def test_explain_jd_mode_prints_both_passes_with_markers(
    fake_dirs, monkeypatch, tmp_path
):
    _no_shape_run(monkeypatch)

    jd = tmp_path / "jd.md"
    jd.write_text("## Essentials\nfrontmatter\n## Summary\nThe role is real.\n")

    result = runner.invoke(
        app, ["eval", str(tmp_path / "resume.pdf"), "--jd", str(jd), "--explain"]
    )

    assert result.exit_code == 0, result.output
    assert "pass: jd-vision" in result.output
    assert "pass: jd-eval" in result.output
    # Each pass should carry at least the preamble source marker
    assert "[from: preamble.md]" in result.output
    assert "[from: task-jd-vision.md]" in result.output
    assert "[from: task-jd-eval.md]" in result.output
    # The JD path is threaded through as its own section source marker.
    # We match the filename fragment since Rich may wrap long paths.
    assert "jd.md]" in result.output
    # The verbatim-content warning is printed (stderr in real use; the
    # CliRunner merges streams).
    assert "review before sharing" in result.output


def test_explain_jd_mode_with_company_path(
    fake_dirs, monkeypatch, tmp_path
):
    _no_shape_run(monkeypatch)

    jd = tmp_path / "jd.md"
    jd.write_text("## Summary\nRole text.\n")
    company = tmp_path / "meridian.md"
    company.write_text("## Meridian AI\nFictional company.\n")

    result = runner.invoke(
        app,
        [
            "eval",
            str(tmp_path / "resume.pdf"),
            "--jd",
            str(jd),
            "--company",
            str(company),
            "--explain",
        ],
    )

    assert result.exit_code == 0, result.output
    # File-path company's filename shows up in the source marker.
    assert "meridian.md]" in result.output
    assert "Fictional company." in result.output


def test_explain_never_triggers_pdf_or_model_validation(
    fake_dirs, monkeypatch, tmp_path
):
    """--explain should work without a PDF, without --model, without config."""
    _no_shape_run(monkeypatch)

    # No config, no --model, no PDF file for phase1-visual — normally all
    # three of those would trip error paths. --explain short-circuits them.
    result = runner.invoke(
        app, ["eval", "--prompt", "phase1-visual", "--explain"]
    )

    assert result.exit_code == 0, result.output
    assert "[config]" not in result.output
    assert "[invocation]" not in result.output
