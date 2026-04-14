"""Output-path resolution + dated-filename + per-eval saver.

Every eval output lands under `config.data_dir() / "runs"` unless the
caller passed an explicit `--output`. Filenames follow
`YYYY-MM-DD-<stem>-<6hex>.<ext>` so same-day runs never collide.

Nothing here writes to CWD. If a test or dev loop wants a file next to
the resume, they pass `--output` explicitly.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from pathlib import Path

from cold_read import config as _config

RUNS_SUBDIR = "runs"


def runs_dir() -> Path:
    """Return `data_dir()/runs`, creating it if absent."""
    path = _config.data_dir() / RUNS_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_output_path(input_stem: str, ext: str = ".md") -> Path:
    """Return a dated, collision-resistant path under the runs dir."""
    return runs_dir() / _dated_filename(input_stem, ext)


def save_individual(
    model_name: str,
    deployment: str,
    prompt_id: str,
    content: str,
    pdf_name: str,
) -> Path:
    """Write one eval result to the runs dir with a markdown header."""
    stem = f"{model_name}-{prompt_id}"
    out_path = runs_dir() / _dated_filename(stem, ".md")

    header = (
        f"# Eval: {model_name} / {prompt_id}\n\n"
        f"**PDF:** {pdf_name}  \n"
        f"**Date:** {datetime.now().isoformat()}  \n"
        f"**Model:** {model_name} ({deployment})\n\n---\n\n"
    )
    out_path.write_text(header + content)
    return out_path


def _dated_filename(stem: str, ext: str) -> str:
    """Build `YYYY-MM-DD-<stem>-<6hex><ext>`."""
    date = datetime.now().strftime("%Y-%m-%d")
    short_id = secrets.token_hex(3)  # 6 hex chars
    if not ext.startswith("."):
        ext = "." + ext
    return f"{date}-{stem}-{short_id}{ext}"
