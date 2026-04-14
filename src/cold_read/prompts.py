"""Loaders for bucket-1 packaged resources (prompts + calibration artifacts).

Everything in this module reads from inside the installed wheel via
`importlib.resources`. No caller should cons up a filesystem path to the
repo layout and pass it in — if it looks like a real path, it is a bug.
"""

from __future__ import annotations

import atexit
import json
from contextlib import ExitStack
from importlib.resources import as_file, files
from pathlib import Path

_RESOURCES = files("cold_read") / "_resources"
_PROMPTS = _RESOURCES / "prompts"

# Fixed images (calibration PNGs) may live inside a zipfile install, in which
# case `as_file()` materializes a temp copy that is cleaned up when the context
# exits. A process-scoped ExitStack holds those contexts open for the lifetime
# of the CLI invocation so callers can treat the returned Paths as stable.
_exit_stack = ExitStack()
atexit.register(_exit_stack.close)


class UnknownPromptError(KeyError):
    """Raised when a phase id is not present in the manifest."""


def load_manifest() -> dict:
    """Return the parsed prompts manifest."""
    return json.loads((_PROMPTS / "manifest.json").read_text())


def load_prompt_file(filename: str) -> str:
    """Return the text of a packaged prompt file by filename."""
    return (_PROMPTS / filename).read_text()


def load_prompt(phase_id: str) -> str:
    """Return the prompt text for a phase id, resolved via the manifest."""
    manifest = load_manifest()
    phase = _find_phase(manifest, phase_id)
    if phase is None:
        available = _phase_ids(manifest)
        raise UnknownPromptError(
            f"Unknown prompt '{phase_id}'. Available: {', '.join(available)}"
        )
    return load_prompt_file(phase["prompt_file"])


def get_fixed_images(phase_id: str) -> list[Path] | None:
    """Return filesystem Paths for a phase's fixed images, or None.

    Paths are guaranteed valid for the lifetime of the process. Does not
    itself read the PNG bytes — callers are expected to open, encode, or
    copy before the process exits.
    """
    manifest = load_manifest()
    phase = _find_phase(manifest, phase_id)
    if phase is None or "fixed_images" not in phase:
        return None

    paths: list[Path] = []
    for img_rel in phase["fixed_images"]:
        traversable = _RESOURCES.joinpath(*img_rel.split("/"))
        paths.append(_exit_stack.enter_context(as_file(traversable)))
    return paths


def get_all_prompt_ids() -> list[str]:
    """Return manifest phase ids, excluding calibration and composable entries.

    Calibration is excluded because it must be run explicitly. Composable
    entries (`jd-eval`) are excluded because they have no standalone prompt
    file — they describe a multi-pass composition that the eval engine
    assembles at runtime.
    """
    manifest = load_manifest()
    return [
        p["id"]
        for p in manifest["phases"]
        if p.get("id")
        and p["id"] != "calibration"
        and not p.get("composable")
    ]


def _find_phase(manifest: dict, phase_id: str) -> dict | None:
    return next((p for p in manifest["phases"] if p.get("id") == phase_id), None)


def _phase_ids(manifest: dict) -> list[str]:
    return [p["id"] for p in manifest["phases"] if p.get("id")]
