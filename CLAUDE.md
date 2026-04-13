# Resume Cold Reader

Sends resume page images to vision models and simulates how a recruiter screens them. Two modes: standalone prompts (visual hierarchy, PM, SWE) and JD-based eval (two-pass: vision then content match).

## Engineering ownership

You own this codebase. When you encounter a code smell while working on a feature, fix it at the root rather than adding another adapter on top. Act as the engineer, not just the implementer: push back when an approach creates debt, ask forward-looking questions about edge cases. Read the existing code before adding — the codebase is ~600 lines.

## Principles

- **One authoritative source.** Prompts are the source of truth for eval behavior. `manifest.json` is the source of truth for phase config. The code composes them; it doesn't duplicate their logic.
- **Wait for three variants before abstracting.** Don't generalize the model registry, prompt composition, or provider support until there's a real reason.

## File layout

```
prompts/         Prompt text files + manifest.json. All prompt loading goes here.
calibration/     Frozen PNGs + answer key for vision model qualification.
examples/        Fictional company dossier and JDs for demo purposes.
src/cold_read/   Python only. CLI entry point + eval engine.
```

## How the composable prompt system works

JD-based evals compose a prompt from parts at runtime:

1. `preamble.md` — recruiter persona, cold-apply context
2. `company-{slug}.md` — company dossier (optional, loaded from `prompts/` by slug or from any file path via `--company`)
3. The JD file itself (passed via `--jd`)
4. `task-jd-eval.md` — evaluation instructions

Two passes run automatically: vision (preamble + `task-jd-vision.md`, no JD) then content (full composition above). Each pass is an independent API call.

## `_get_project_root()` assumption

The tool finds its prompts and calibration files by walking up from `__file__` to find `pyproject.toml` + `prompts/`. This works for editable installs (`uv pip install -e .`) and running from within the project directory. For other setups, set `COLD_READ_HOME` to the project root.
