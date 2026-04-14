---
date: 2026-04-14
topic: install-story
---

# Install-Story Bundle

## Problem Frame

The `README.md` and `CLAUDE.md` on the `initial-tune-up` branch describe a standalone open-source tool a stranger can install from PyPI with `uv tool install resume-cold-read`, configure their own provider credentials, and run without reading source code. The code does not yet deliver that story. Today the tool walks up from `__file__` looking for `pyproject.toml` + `prompts/`, falls over if `COLD_READ_HOME` is not set, hardcodes a maintainer-specific Azure deployment name as the default, treats `AZURE_PRIMARY_*` and `AZURE_SECONDARY_*` as canonical env var names, expects the caller to know which env vars each registered model needs, writes output relative to the caller's CWD, and shells out to the `claude` CLI in a subprocess hack. All of this works for the maintainer; none of it works for a stranger.

Two audiences are affected. **End users** installing from PyPI need a working first-hour experience: pick a provider, configure credentials, run an eval. **The maintainer** needs calibration against every registered model to keep working — that workflow (new model ships → run calibration → decide whether to trust it → adjust prompts) is how the project stays credible as new vision models release.

The architectural bones are already in the code (`MODELS` registry, `client_type` capability dispatch in `_build_client`, env-var-driven credential resolution in `src/cold_read/eval.py`). The work is to *expose*, *rename*, and *relocate* what exists, plus add two new UX commands (`init`, `doctor`) and route packaged-resource reads through `importlib.resources`.

## Requirements

**Packaging & distribution**

- **R1.** The PyPI package name and the CLI command both become `resume-cold-read`. Users install with `uv tool install resume-cold-read` and invoke `resume-cold-read <subcommand>` in the shell. `pyproject.toml` and all documentation update consistently.
- **R2.** Packaged resources (`prompts/`, `calibration/`) ship inside the wheel. All reads of those resources go through `importlib.resources`. The `_get_project_root()` function and the `COLD_READ_HOME` environment variable are deleted. No code path reads packaged resources from the filesystem relative to `__file__` or CWD.
- **R3.** User-owned persistent configuration lives at `~/.config/resume-cold-read/` (resolved via `platformdirs` for cross-platform correctness). Contents: `.env` (credentials), `config.toml` (default model, per-provider deployment mappings), and `companies/` (user-authored company profiles, one markdown file per slug).
- **R4.** The default output directory becomes the user data dir (via `platformdirs` — e.g., `~/.local/share/resume-cold-read/runs/` on Linux). Output filenames follow the pattern `YYYY-MM-DD-<input-stem>-<short-id>.md`. The `--output` / `-o` flag still overrides. No code path writes to the process's current working directory by default.

**Provider & model registry**

- **R5.** Providers are represented as capability-keyed shapes, not stringly-typed `client_type` branches. Five shapes exist: `openai` (native API, default on-ramp for new users), `azure-openai`, `azure-maas` (for Azure AI Foundry MaaS models like Grok), `claude-cli` (preserves the current `claude` subprocess path for users on a Claude subscription), and a reserved `anthropic` placeholder (not implemented this pass). Each shape declares which credential fields it needs.
- **R6.** Model aliases are decoupled from Azure deployment names. The registry maps a model alias (e.g., `gpt52`) to a provider shape (`azure-openai`) and any shape-specific defaults. Azure deployment names live in user `config.toml` (e.g., `[providers.azure-openai] deployment_map = { gpt52 = "gpt-52-chat" }`), not in code. A second user with a different deployment edits configuration, not source.
- **R7.** The default model is user-configurable via `config.toml` (`default_model` key), set by `resume-cold-read init` based on which providers the user configured. The `--model` flag continues to override per-invocation. When `--model` is omitted and `default_model` is unset, the tool exits with a message pointing at `init`.
- **R8.** Environment variable names describe the provider, not its position in the maintainer's setup: `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT`, `AZURE_MAAS_API_KEY` + `AZURE_MAAS_ENDPOINT`. `AZURE_PRIMARY_*` and `AZURE_SECONDARY_*` are retired. `.env.example` at the repo root reflects the new names.
- **R9.** Every currently-registered model keeps working: `gpt52`, `grok4`, `claude-sonnet`, `claude-opus`. The `claude` CLI subprocess path is preserved as-is inside the `claude-cli` provider shape. Calibration runs against any configured provider (`resume-cold-read eval --prompt calibration --model <alias>`) and is load-bearing — the ability to register and calibrate new models as they ship is a first-class, expected event.

**First-run UX**

- **R10.** `resume-cold-read init` is an interactive wizard that configures one provider at a time with a "configure another provider?" loop. It writes credentials to `~/.config/resume-cold-read/.env` and non-secret config (selected providers, deployment mappings, default model) to `~/.config/resume-cold-read/config.toml`. It tests credentials with a lightweight live call before writing — a wizard that claims success when the key is wrong is worse than no wizard.
- **R11.** For the `azure-openai` shape, `init` queries the `/openai/deployments` endpoint on the user's resource and presents a pick-list of detected deployments, filtering to vision-capable ones. If the listing call fails (wrong endpoint, wrong API version, insufficient permissions), the wizard falls back to free-form deployment-name entry with a one-line note ("Couldn't list deployments automatically; enter the name yourself"). The wizard does not teach Azure configuration — it uses what the user already has.
- **R12.** `resume-cold-read doctor` is a diagnostic command that reports on four sections: **Install** (packaged resources importable, `pdftoppm` on `PATH`), **Config** (config dir exists, `.env` present), **Providers** (each configured provider runs a live credential-resolution check), and **Models** (which aliases are enabled based on resolved credentials, which is the default). Output uses Rich's green/red checklist style (Rich is already a dependency). Exits 0 when everything critical is green; exits non-zero when any critical item is red.
- **R13.** When a command requires configuration and none exists (no config dir, no `.env`, no resolvable credentials), the tool exits non-zero with a one-line message pointing at `resume-cold-read init`. No interactive prompt is launched implicitly — CLI convention is that interactivity is user-initiated.

**Error & output experience**

- **R14.** User-facing errors name the artifact bucket the missing thing belongs to (ships-with-package / user-owned / per-invocation), include the specific path checked, and suggest the corresponding fix path (reinstall / edit config or run `init` / check the CLI argument). The bucket labels match the three-bucket model documented in `CLAUDE.md`.
- **R15.** `resume-cold-read eval ... --explain` assembles the full composed prompt (preamble + company profile + JD + task), prints it with source-file markers indicating which file each section came from, and exits without calling any API. Works for both manifest-driven phases and JD-composable mode.

## Success Criteria

- A first-time user on a clean macOS or Linux system, starting from zero knowledge of the codebase, can run `uv tool install resume-cold-read` → `resume-cold-read init` → `resume-cold-read doctor` → `resume-cold-read eval resume.pdf --jd role.md` and reach a written report without reading source code, setting any environment variable manually, or touching the repo.
- The maintainer's existing calibration workflow continues to work with no loss of coverage: `resume-cold-read eval --prompt calibration --model <alias>` runs against each of `gpt52`, `grok4`, `claude-sonnet`, and `claude-opus` after configuration in `init`, producing the same reports the current code produces.
- `_get_project_root()` is deleted. `COLD_READ_HOME` is deleted. No code path reads packaged resources from outside the wheel. No code path writes output to CWD by default.
- `resume-cold-read doctor` can be run from any directory on any machine with the package installed and returns an accurate picture of install + config + provider + model status.
- Reinstalling the package via `uv tool install --force resume-cold-read` on a clean machine recovers the "broken install" failure mode cleanly — bucket-1 errors point at reinstall, not at a missing env var.

## Scope Boundaries

Everything in this list is deferred to a future iteration and captured in `docs/ideation/2026-04-14-open-ideation.md`. None of these should land in this work even if tempting:

- Full structured-response contract (task prompts emitting JSON) and run-as-directory output with separate response/metadata/composed-prompt files. This pass ships a single `.md` file per run, just routed to the user data dir.
- Auto-graded calibration against a structured answer key. The user continues to grade calibration output against `calibration/answer-key.md` by hand.
- Meta-eval fixture set / regression scoring on prompt changes.
- Watch mode (`resume-cold-read watch`), application-folder reframe (resume + JD + company + runs in one user-owned directory), community profile registry, keychain-backed credentials.
- Native Anthropic SDK provider. The reserved `anthropic` shape exists in the registry but is not implemented — Claude users continue to use `claude-cli`.
- Gemini support. The README's calibration table includes Gemini ("web only") as historical data, not as a supported runtime provider.
- The PyPI publish workflow itself (classifiers, release automation, trusted publisher configuration). That lands in a separate commit or PR after the install-story code is in place and verified locally.

## Key Decisions

- **OpenAI first-class, Azure peer.** The default on-ramp for a new user is native OpenAI. Azure OpenAI remains a supported peer provider (same SDK, different base URL) but is no longer positioned as primary. Reason: Azure-primary is a maintainer artifact; strangers installing from PyPI are more likely to have an OpenAI key.
- **Package AND command both rename to `resume-cold-read`.** Consistency between install name and invocation name is worth the docs sweep. The short `cold-read` alias is not preserved.
- **Env vars / `.env` only.** No keychain, no OS-specific credential stores. Reason: keeps the install story single-path and avoids platform-specific backend complexity. Keychain support is an iterate-from-there candidate.
- **The `claude` CLI subprocess path is preserved as-is** under the new `claude-cli` provider shape. Adding native Anthropic SDK support would be a cleaner architecture but changing it now is out of scope.
- **All four existing providers stay.** Calibration across providers is a load-bearing maintenance workflow — new vision models ship continuously and the ability to run the calibration suite against them is how prompt quality stays healthy. Dropping providers to simplify the codebase is the wrong simplification.
- **Azure deployment interrogation in `init` with graceful fallback.** The `/openai/deployments` endpoint is queried with a short timeout; on any failure the wizard falls back to free-form entry without attempting to diagnose Azure configuration. The project does not become an Azure tutorial.
- **Config dir layout: `~/.config/resume-cold-read/` for user-owned persistent, `~/.local/share/resume-cold-read/runs/` for output.** Resolved via `platformdirs` (Linux XDG, macOS Application Support, Windows APPDATA). Two separate directories because config and output have different lifecycles — config is sticky, output accumulates.
- **First-run with no config = error + pointer to `init`**, not an auto-launched wizard. CLI convention: interactivity is user-initiated.
- **Model registry stays Python-side in this pass.** Users enable/configure any of the registered providers, override Azure deployment names, and set a default — but cannot register brand-new model aliases without editing code. User-extensible model registration is an iterate-from-there candidate.

## Dependencies / Assumptions

- `platformdirs` is added as a runtime dependency. It is widely adopted, has no sharp edges for this use case, and replaces any hand-rolled XDG handling.
- `rich` and `typer` are already dependencies and are leaned on for the `init` and `doctor` UI (checklists, live credential-testing feedback). No new UI framework is introduced.
- The Azure OpenAI deployments API (`GET {endpoint}/openai/deployments`) is reachable with the user's key. API version is pinned in a single config point that can be updated as Azure evolves the endpoint.
- `pdftoppm` (from `poppler`) is a runtime prerequisite and will continue to be surfaced in the README and validated by `doctor`. This pass does not attempt to remove the rasterization step.
- No database, no server, no telemetry. The tool remains a one-shot CLI with local file I/O.

## Visual Aid

Artifact-bucket to filesystem-location mapping after this work lands. The current code collapses all three buckets into "stuff in a source tree," which is the root cause of most install-story bugs.

| Bucket | Contents | Location on a user's machine |
|---|---|---|
| 1. Ships with the package | `prompts/*.md`, `prompts/manifest.json`, `calibration/*.png`, `calibration/answer-key.md` | Inside the installed wheel, read via `importlib.resources` |
| 2. User-owned persistent | `.env` (credentials), `config.toml` (default model, deployment mappings), `companies/<slug>.md` (user-authored profiles) | `~/.config/resume-cold-read/` (via `platformdirs`) |
| 3. Per-invocation | Resume PDF, JD file, output path | CLI arguments; output defaults to `~/.local/share/resume-cold-read/runs/` |

## Outstanding Questions

### Resolve Before Planning

None. All product decisions are resolved.

### Deferred to Planning

- [Affects R2][Technical] Whether to physically relocate `prompts/` and `calibration/` under `src/cold_read/_resources/` versus keeping them at repo root and using `hatch force-include` to pull them into the wheel. Physical relocation is cleaner long-term; `force-include` preserves the current repo layout. Either produces the same runtime behavior via `importlib.resources`.
- [Affects R5, R6][Technical] Exact method signatures on the `Provider` protocol. Current capability dispatch uses a `client_type` string; the replacement needs enough structure to handle the `claude-cli` subprocess path alongside the three `openai`-SDK-shaped providers without leaking one shape's assumptions into another.
- [Affects R10, R11][Needs research] Mechanism for the Azure OpenAI deployments listing call — use the `openai` SDK client's `models.list()` path against the Azure endpoint, or raw HTTP via `httpx` (already transitively present via the `openai` SDK)? Affects error handling and version-pinning strategy.
- [Affects R11][Needs research] How to detect "vision-capable" from the deployments listing response. Azure returns deployment metadata including the underlying model; the mapping from model family to vision capability needs to be either a small hardcoded allow-list (simpler, needs periodic updates) or derived from a model-metadata field (more robust if Azure exposes it).
- [Affects R10, R12][Technical] What constitutes a "live credential test" per provider shape. For `openai` and `azure-openai`, a cheap call like listing models works. For `azure-maas`, the equivalent endpoint may differ. For `claude-cli`, the test is "`claude` is on PATH and responds to `--version`."
- [Affects R3, R7][Technical] Whether existing users need a migration path from v0.1.0's implicit CWD-based setup to the new config dir. Probably not — the package is pre-1.0 and the installed base is effectively the maintainer — but worth confirming the migration is a no-op.
- [Affects all][Technical] Order of operations for the refactor. Loader protocol first, provider protocol second, config-dir + init + doctor on top? Or vertical slice per provider shape? Affects reviewability and intermediate-state testability.

## Next Steps

→ `/ce:plan` for structured implementation planning.
