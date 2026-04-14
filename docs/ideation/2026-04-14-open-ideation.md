---
date: 2026-04-14
topic: open-ideation
focus: open-ended — grounded in the `initial-tune-up` branch context (docs describe the install story; code has to catch up)
---

# Ideation: Open-ended — resume-cold-read standalone install story

Scope set during review: the through-line is "clean this up to be a real thing somebody can install, then iterate from there." Ideas that serve cleanup-to-shippable rank above ideas that reshape the product.

## Codebase Context

**Project shape.** Open-source vision-model recruiter simulator on branch `initial-tune-up`. One commit ahead of main. ~630 lines of Python: `eval.py` is a 614-line monolith holding the model registry, prompt loading, PDF-to-PNG conversion, client building, JD composition, and output writing; `cli.py` is a 17-line Typer shim. `prompts/` and `calibration/` sit at repo root (not yet in `src/cold_read/`).

**What the code actually does today.**
- Two prompt-loading code paths: manifest-driven phases (`calibration`, `phase1-visual`, `phase2-pm`, `phase2-swe`) and inline JD composition. The manifest has a JD entry the JD path ignores.
- Prompt discovery via `_get_project_root()` (walks up from `__file__` looking for `pyproject.toml` + `prompts/`) with a `COLD_READ_HOME` override.
- Hardcoded `MODELS` dict tangling model id, Azure deployment name, and env var keys per entry. Azure primary, Azure secondary (for Grok MaaS), and `claude_cli` (subprocess shelling out to the Claude CLI with `--system-prompt`, stripping `CLAUDECODE`, parsing JSON stdout, token counts return 0).
- No native OpenAI. No version field anywhere (prompts, manifest, models).
- `pdftoppm` at hardcoded 150 DPI; tempfiles leak. Output default assumes CWD is the repo.
- Calibration: frozen two-page resume with intentional traps (header/footer name mismatch, page counter "3" on page 2, diacritics, 8pt text), 18 questions across three tiers, graded by the user against `answer-key.md` by hand.

**Stance from CLAUDE.md.** Three-bucket artifact model: (1) ships-with-wheel — prompts, manifest, calibration images/key; (2) user-owned persistent — company profiles, credentials, provider config; (3) per-invocation — resume PDF, JD, output path. Buckets don't collude. Two audiences: end users installing from PyPI, and developers on the code. Meridian AI is the fictional demo universe (Contoso).

**Leverage points observed.** Loader seams that currently filesystem-walk (prompts, manifest, calibration, dossiers) would all flow through one `importlib.resources`-backed loader if refactored. `client_type` switch is shallow — capability-keyed providers would make the third variant (OpenAI) a config entry, not a code branch. The manifest + composable prompt system is only a year old; phase1/phase2 predate it.

## Ranked Ideas

### 1. Structured run-as-directory with response contract and content-hashed prompts
**Description:** Each invocation writes a directory (not a single `.md`) under a user data dir (e.g., `~/.local/share/resume-cold-read/runs/<run-id>/`) containing: the input PDF (hash-addressed), the composed prompt, per-phase structured responses (JSON emitted by a contract every task prompt ends with — fixed keys: `concerns[]`, `strengths[]`, `scores{}`, `narrative_markdown`), the rendered report, and `metadata.json` (package version, prompt-bundle sha, model id, token counts, timings). Markdown becomes a renderer over the JSON.
**Rationale:** Every bold downstream idea (diff between resume revisions, meta-eval on prompt edits, jury/bake-off, telemetry leaderboard, GitHub Action) wants the full run tuple. Today the tool throws that tuple away. Also kills the `pdftoppm` tempfile leak, makes Claude's `tokens=0` lie visible, makes silent drift between package versions diagnosable, and fixes the CWD-is-the-repo output default as a side effect.
**Downsides:** Every task prompt has to be revised to emit the contract. Response parsing failures need a loud fallback. Contract design is load-bearing — a bad schema is worse than no schema.
**Confidence:** 90%
**Complexity:** Medium
**Status:** Explored (2026-04-14 — the output-dir-routing piece folds into the install-story brainstorm; full structured-contract work deferred)

### 2. Loader protocol + capability-keyed provider registry (with library/CLI split)
**Description:** Define a `Loader` protocol (`get_text`, `get_bytes`, `list`) with three implementations — `PackageLoader` via `importlib.resources`, `UserConfigLoader` via `platformdirs`, `InvocationLoader` for CLI args. Every consumer in `eval.py` takes a loader, not a path. In parallel, replace the hardcoded `MODELS` dict + `client_type` switch with a `Provider` protocol keyed by capability (`supports_pdf_direct`, `max_image_dim`, `send_vision`). Carve `cold_read.engine` (pure) from `cold_read.cli` (thin).
**Rationale:** Collapses four filesystem walks into one seam. Makes the three-bucket stance mechanically enforceable — pass the wrong loader, get the wrong bucket, full stop. Delivers the in-flight punch list as a side effect. The third provider case (claude_cli) already exists, so the "wait for three variants" rule is satisfied. The library/CLI split unblocks every "what if it weren't a CLI" follow-on (GitHub Action, notebook, watch mode, web UI).
**Downsides:** Largest single change in the punch list. Touches nearly every function in `eval.py`. Over-abstracting is a real risk if done before the output contract (#1) is settled — the engine's return type should be the Run artifact.
**Confidence:** 85%
**Complexity:** High
**Status:** Explored (2026-04-14 — selected as the core of the install-story brainstorm)

### 3. Calibration-as-framework: auto-graded, structured answer key, opt-in leaderboard telemetry
**Description:** Promote `calibration/` from project-internal fixture to a first-class subsystem. Ship `answer-key` as structured data (JSON/YAML) matching the response contract from #1, so `cold-read calibrate <model>` emits a numeric tier-A/B/C score without human grading. Expose it as `cold_read.calibration` — a generic "does this vision model actually read this document" harness other projects could adopt (invoices, contracts, medical forms are obvious follow-on presets). Add `--share` to emit an anonymized bundle (model id, prompt hash, scores only — no resume content) so the README's static model table becomes a community-maintained leaderboard.
**Rationale:** The calibration pattern (frozen document + traps + tiered answer key → score) is the project's most transferable IP and it's currently hiding behind a resume tool. Auto-grading removes the manual-grading bottleneck that gates every prompt or model change. Leaderboard telemetry makes the project authoritative on vision-reliability benchmarks as new models land.
**Downsides:** Formalizing the framework tempts premature generalization — must stay resume-grounded until a real second preset shows up. Leaderboard implies hosting or upload flow, which is new operational surface.
**Confidence:** 75%
**Complexity:** Medium for auto-grade alone; High for framework + leaderboard
**Status:** Unexplored — iterate-from-there

### 4. Meta-eval fixture set — prompt edits show a regression number
**Description:** Ship a small fixture set of `(resume, JD, expected-concerns)` tuples and a `cold_read.meta_eval` runner that scores whether the current prompts catch the expected concerns. Runs in CI on every PR touching `prompts/`. Tier-C from calibration, applied to the eval output itself.
**Rationale:** Prompt edits today are vibes-tuned. A fixture set converts "does this change improve things?" into a number. Forces the response contract to be structured enough to grade, which compounds with every later feature.
**Downsides:** Fixture curation is real work — bad fixtures lock in bad behavior. Depends on #1 for structured output.
**Confidence:** 70%
**Complexity:** Medium
**Status:** Unexplored — iterate-from-there

### 5. First-run install story bundle: `doctor` + `init` wizard + bucket-named errors + `--explain`
**Description:** Four tightly-connected UX features for the "someone just ran `uv tool install`" path:
- `cold-read doctor` — checks config dir, resolves creds per provider with live pings, verifies `pdftoppm`, validates packaged prompts are importable. Green/red checklist with exact remediation strings.
- `cold-read init` — interactive first-run wizard picks a provider, asks for 2-3 fields, tests creds live, writes `~/.config/resume-cold-read/.env` and `config.toml`.
- Every user-facing error names its bucket (bucket-1 missing → "your install is broken"; bucket-2 missing → "config dir"; bucket-3 missing → "CLI arg"), making the CLAUDE.md stance visible.
- `--explain` — dry-run that prints the composed prompt with source-file markers and exits, so users and contributors can debug without burning API calls.
**Rationale:** The README now promises a working install story. This is what makes it true for a stranger's first hour. Today the first failure mode is a wall of Azure SDK stack traces. These four together convert "it doesn't work" into "line 3 is red."
**Downsides:** Most pedestrian of the survivors — no bold reframe, just polish. But it's the polish without which the install story is a promise the tool can't keep.
**Confidence:** 80%
**Complexity:** Medium
**Status:** Explored (2026-04-14 — bundled into the install-story brainstorm with #2)

### 6. Watch mode — the resume as an editable document under continuous cold-read
**Description:** `cold-read watch resume.pdf --jd posting.md` sits on the file, re-runs on save, maintains a delta ("4 of 7 original flags resolved; 1 new flag introduced by this edit"). `pytest --watch` for a resume.
**Rationale:** The current one-shot CLI treats the resume as a finished artifact; in reality users iterate on it for hours. Watch mode flips the tool from "audit event" to "editing companion" — a fundamental shape change.
**Downsides:** Depends on #1 and #2. Requires real diff across runs — without structured output it's just re-printing prose. Most likely to scope-creep into a TUI.
**Confidence:** 60%
**Complexity:** Medium (if #1 and #2 are in place); High otherwise
**Status:** Unexplored — iterate-from-there

### 7. Application-folder as the unit of work (emerged during review)
**Description:** Treat a job application as a filesystem folder: `resume.pdf`, `jd.md`, and optional `company.md` sit together in a user-owned directory, with runs stored in a `.cold-read/runs/` subfolder next to them. The CLI discovers inputs by convention (like `terraform init` or `git`), so `cd ~/job-hunt/meridian-swe && cold-read` runs without flags. Six weeks later, the user re-runs and diffs against the previous verdict.
**Rationale:** Gives the user a mental model ("an application is a folder") that's obvious from the filesystem. Kills the CWD-is-the-repo assumption more thoroughly than #1 alone. Bigger product-shape idea than the install story — genuinely reframes how the tool is used.
**Downsides:** Bigger than cleanup-to-shippable scope. Introduces a new user convention that would need documentation, migration story, and careful interaction with bucket-2 (where does the shared company profile live if one lives next to a specific application?). Better as the first iterate-from-there move after shipping.
**Confidence:** 70%
**Complexity:** High
**Status:** Unexplored — deliberately deferred as first iterate-from-there candidate after install story lands

## Rejection Summary

| # | Idea | Reason Rejected |
|---|------|-----------------|
| 1 | Drop Claude CLI subprocess hack (standalone) | Subsumed by #2's provider-adapter refactor |
| 2 | Drop `pdftoppm` entirely (native PDF only) | Capability-keyed providers in #2 handle this generically; premature to remove fallback |
| 3 | Kill two-pass vision/content split | Changes the product, not the scaffolding — brainstorm variant |
| 4 | Remove manifest, prompts self-describe | Premature; loader refactor reaches the same cleanup |
| 5 | Remove `--company`, fold into JD | Inverts a load-bearing bucket-2 stance from CLAUDE.md |
| 6 | Auto-detect company from JD | Low-value cleverness; JDs don't reliably name the company cleanly |
| 7 | Output a patch against resume source (LaTeX/Typst) | Huge scope; assumes access to source user may not have — brainstorm variant |
| 8 | JD is under test, not the resume / resume grades the JD | Different product, not improvement — brainstorm variant (fork) |
| 9 | User is the recruiter, not the candidate | Product repositioning — brainstorm variant |
| 10 | Auto-bake-off / model jury as the product | Enabled by #1; elevates to feature once structured output lands |
| 11 | GitHub Action: cold-read on PR | Enabled by #2 (library split); premature as standalone |
| 12 | Community profile registry, git-backed | Premature — no users yet to contribute |
| 13 | Company profile generator (from URL/JD) | Niche; enabled by loader refactor as follow-on |
| 14 | Persona gallery / marketplace | Too small to elevate; natural follow-on once loader seam exists |
| 15 | Streaming progress + cost preflight | Pure polish; real but not keystone |
| 16 | Deterministic rerun IDs / session folder (standalone) | Subsumed by #1 run-as-directory |
| 17 | Version/hash everything (standalone) | Subsumed by #1 content-hashed prompts |
| 18 | Bucket-named errors / `--explain` / init / doctor (standalone) | Folded into #5 bundle |

## Session Log
- 2026-04-14: Initial ideation — 4 parallel sub-agents (user-pain, inversion, assumption-breaking, leverage frames) generated 43 raw ideas across frames. 18 rejected, 6 survivors after merging cross-cutting combinations. A seventh survivor (#7, application-folder reframe) emerged during user review of the survivors and was added to the record.
- 2026-04-14: User set scope as "clean this up to be a standalone tool somebody can install, then iterate." Selected the install-story bundle — **#2 (loader + provider registry) + #5 (doctor + init + bucket errors + --explain) + the output-dir-routing piece of #1** — as the seed for `ce:brainstorm`. Ideas #3, #4, #6, and #7 deferred as iterate-from-there candidates.
