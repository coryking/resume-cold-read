# Resume Cold Reader

Vision-model recruiter simulator. Takes a resume PDF (and optionally a JD and company profile), returns the kind of screening reaction a cold-apply recruiter would have.

## Stance

This is an open-source package with a maintainer, not a personal tool that happens to be public. Two audiences consume this project: **end users** who install it and want it to work out of the box, and **developers** working on the code. Code, prompts, defaults, and docs should make sense to someone who showed up yesterday and has never met the maintainer. Maintainer identity belongs in `LICENSE`, `authors`, and any credits screen — it does not leak into voice, defaults, or assumed environment.

Three falsifiable tests:

- Prompts, docs, or error messages using "I/my" or naming a specific real company/role are wrong unless clearly labeled as examples.
- Defaults that assume a specific cloud deployment, filesystem layout, or `.env` location are wrong.
- Content under `examples/` and company-specific sample prompts use the **Meridian AI** demo universe (this project's Contoso). Code must not special-case demo-universe content.

## Artifact buckets

Every file belongs to exactly one of three buckets. They do not collude:

| Bucket | Contents | Lives at install time in |
|---|---|---|
| **Ships with the package** | System prompts, manifest, calibration images/key | The installed wheel, loaded via `importlib.resources` |
| **User-owned persistent** | Company profiles, credentials, provider config | User config dir (`~/.config/resume-cold-read/`) + env vars for secrets |
| **Per-invocation** | Resume PDF, JD, output path | CLI arguments |

A feature that reads bucket-2 data from a bucket-1 location (e.g. loading a company profile from packaged prompts) is a bug. Each bucket has its own loader, and credentials never live in a file that could get committed.

## Engineering ownership

You own this codebase. When a code smell surfaces while working on a feature, fix it at the root rather than adding another adapter on top. Push back when an approach creates debt. Read the existing code before adding — it is ~600 lines.

## Principles

- **One authoritative source.** Prompts are the source of truth for eval behavior. `manifest.json` is the source of truth for phase config. The code composes them; it does not duplicate their logic.
- **Wait for three variants before abstracting.** The model registry, prompt composition, and provider support stay concrete until a third real case shows up.

## File layout

```
prompts/         Bucket 1. System prompts + manifest. Ships in the wheel.
calibration/     Bucket 1. Frozen test images + answer key. Ships in the wheel.
examples/        Meridian AI demo-universe content. Illustrative; not loaded by default.
src/cold_read/   CLI + eval engine (Python).
```

## How the composable prompt system works

JD-based evals compose a prompt at runtime from:

1. `preamble.md` — recruiter persona, cold-apply context (bucket 1)
2. Company profile (bucket 2, optional) — `--company` accepts a slug or a path
3. JD file (bucket 3) — `--jd`
4. `task-jd-eval.md` — evaluation instructions (bucket 1)

Two passes run automatically: vision (`preamble.md` + `task-jd-vision.md`, no JD) then content (full composition above). Each pass is an independent API call.

The `phase1-*` / `phase2-*` prompts predate the composable system. They are self-contained sample prompts using the Meridian AI demo universe — reference implementations for what a full company-specific prompt looks like, not general-purpose content. Real use goes through `--jd`.

## Calibration artifact

The calibration images are a real rendered resume with intentional traps (header/footer name mismatch, page counter showing "3" on page 2, diacritical characters in repo names, small-point-size text). The traps only work on a realistic document, so the calibration resume is legitimately fixed personal content — do not generalize it into a synthetic fixture or the tier-B and tier-C tests lose their meaning.
