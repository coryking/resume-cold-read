# Resume Cold Reader

Sends rendered resume pages as images to a vision model and gets back the reaction a cold-apply recruiter would have. Built around a specific screening dynamic: the model is told it is looking at the resume the way someone grinding through 200 applications looks at it — scanning for the first reason to pass, not the first reason to say yes. Includes a calibration suite that verifies a model can actually read the document before you trust its opinions.

## Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) (recommended) or `pipx`
- `pdftoppm` from [poppler](https://poppler.freedesktop.org/) — `brew install poppler` on macOS, `apt install poppler-utils` on Linux
- API access to a vision-capable model. Azure OpenAI (GPT-5.2 class) is the currently-recommended provider. See [Models](#models) for the full list.

## Install

```bash
uv tool install resume-cold-read
```

This installs the `resume-cold-read` command into an isolated environment and puts it on your `PATH`.

Alternatives:

```bash
# Using pipx
pipx install resume-cold-read

# One-off run without installing
uvx resume-cold-read eval --help
```

## Configure

Credentials live in environment variables. Export them in your shell, or put them in a `.env` file in your working directory or at `~/.config/resume-cold-read/.env` (checked in that order).

```bash
# Azure OpenAI — primary vision model
AZURE_PRIMARY_API_KEY=...
AZURE_PRIMARY_ENDPOINT=https://your-resource.openai.azure.com/

# Azure OpenAI — secondary (optional, for MaaS models like Grok)
AZURE_SECONDARY_API_KEY=...
AZURE_SECONDARY_ENDPOINT=...
```

Run `resume-cold-read eval --list-models` to see all supported models and the env vars each one requires.

## Calibrate once per model

Before trusting a model's evaluations, verify it can read a document accurately. Run the calibration suite one time per model:

```bash
resume-cold-read eval --prompt calibration
```

Grade the output against the answer key (shipped with the package under `calibration/answer-key.md`; also viewable on [GitHub](https://github.com/coryking/resume-cold-read/blob/main/calibration/answer-key.md)). If a model cannot read a footer name or an 8pt email address, its content evaluations are not trustworthy.

## Evaluate a resume against a job description

Two passes run automatically: a **visual pass** (does the layout survive a 10-second recruiter scan?) followed by a **content pass** (does the resume address what the JD asks for?).

```bash
resume-cold-read eval path/to/resume.pdf --jd path/to/job-description.md
```

Adding a company profile sharpens the content pass by grounding the screener in that company's hiring bar, tech stack, and culture:

```bash
resume-cold-read eval path/to/resume.pdf \
  --jd path/to/job-description.md \
  --company path/to/company-profile.md
```

`--company` accepts either a file path or a slug that resolves to `~/.config/resume-cold-read/companies/{slug}.md`.

## Company profiles

Company profiles live in `~/.config/resume-cold-read/companies/`. Creating one profile per company you are applying to substantially improves the content pass — the screener has real context about what this specific company values rather than evaluating against a generic "tech company" lens.

See [examples/companies/meridian-ai.md](examples/companies/meridian-ai.md) for a demo profile. Meridian AI is this project's fictional demo company (think Contoso for recruiting simulations).

## Models

```bash
resume-cold-read eval --list-models          # Available models and their env vars
resume-cold-read eval --model grok4          # Pick a specific model
resume-cold-read eval -o result.md           # Custom output path
```

Claude models (`claude-sonnet`, `claude-opus`) run through the [Claude CLI](https://claude.ai/code) rather than an API key. Install the CLI if you want to use them.

Results from one calibration run (18 questions across three difficulty tiers, total possible 14):

| Model | Tier A (5) | Tier B (4) | Tier C (5) | Total /14 |
|-------|-----------|-----------|-----------|-----------|
| GPT-5.2 | 5 | 4 | 3.5 | **12.5** |
| Gemini (web only) | 5 | 4 | 3.5 | **12.5** |
| Claude Sonnet | 5 | 2 | 2 | 9 |
| Claude Opus | 4.5 | 1.5 | 2 | 8 |
| Grok 4 | 5 | 0 | 1.5 | 6.5 |

Recalibrate with your own provider and model versions — these scores drift as models update.

## Sample standalone prompts

The `--prompt` flag runs one of a handful of sample prompts that don't require a JD:

```bash
resume-cold-read eval resume.pdf --prompt phase1-visual   # Visual / information architecture
resume-cold-read eval resume.pdf --prompt phase2-pm       # PM-lens content eval (demo universe)
resume-cold-read eval resume.pdf --prompt phase2-swe      # SWE-lens content eval (demo universe)
```

`phase1-visual` is role-agnostic and useful for a quick layout check. The `phase2-*` prompts use the Meridian AI demo universe and are intended as reference implementations — they show what a full company-specific prompt looks like. For real use, compose your own with `--jd` and `--company`.

## Prompt architecture

JD-based evals compose a prompt at runtime from four parts:

1. **Preamble** — recruiter persona, cold-application context, negativity bias framing
2. **Company profile** (optional) — what the company does, tech stack, hiring bar, culture
3. **Job description** — the actual role requirements
4. **Task** — rate each resume section a/b/c/d, identify gaps, make a decision

The vision pass uses a different task (eye-tracking simulation, squint test, recall test) and skips both company and JD — it evaluates the document as a visual artifact first.

## Calibration details

The calibration suite tests whether a vision model can accurately read a rendered document before you trust it to evaluate content. A frozen two-page resume image contains intentional traps:

- Fake identity elements (misspelled name, nonsense email domain, unexpected phone format)
- A footer name that does not match the header name
- A page counter showing "3" on page 2
- GitHub repo names with diacritical characters
- Small-point-size text that tests OCR resolution

18 questions across three difficulty tiers test reading accuracy. Models that can't read the traps reliably will produce evaluations that sound confident but are grounded in misreadings.

## License

BSD-3-Clause. See [LICENSE](LICENSE).
