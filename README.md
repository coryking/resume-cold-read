# Resume Cold Reader

Sends rendered resume pages as images to a vision model and evaluates them the way a recruiter would — scanning for the first reason to say no. Includes a calibration system that verifies whether the model can actually read the document before trusting its opinions.

## Prerequisites

- **Azure OpenAI deployment** with a vision-capable model (GPT-5.2 or similar). See [Azure OpenAI docs](https://learn.microsoft.com/en-us/azure/ai-services/openai/).
- **pdftoppm** (part of [poppler](https://poppler.freedesktop.org/)) for PDF-to-image conversion. Install via `brew install poppler` (macOS) or `apt install poppler-utils` (Linux).
- **Claude CLI** (optional) — only needed if using `claude-sonnet` or `claude-opus` models. Install from [claude.ai/code](https://claude.ai/code).

## Install

```bash
git clone https://github.com/coryking/cold-read.git
cd cold-read
uv pip install -e .
```

## Configure

Copy `.env.example` to `.env` and fill in your Azure OpenAI credentials:

```bash
cp .env.example .env
```

See `cold-read eval --list-models` for which env vars each model needs.

## Usage

### Calibrate a model (run once per model)

Verify the model can accurately read document text before trusting its evaluations:

```bash
cold-read eval --prompt calibration
```

Grade the output against `calibration/answer-key.md`. If the model can't read an 8pt email address or misreads a name in the footer, its content evaluations aren't trustworthy.

### Evaluate a resume against a job description

Two-pass eval: visual hierarchy first (does it survive a 10-second scan?), then content match (does it address the JD requirements?).

```bash
cold-read eval my-resume.pdf --jd examples/job-descriptions/senior-swe.md
```

With a company dossier for additional context:

```bash
cold-read eval my-resume.pdf \
  --jd examples/job-descriptions/senior-swe.md \
  --company examples/companies/meridian-ai.md
```

The `--company` flag accepts a file path or a slug (looks in `prompts/company-{slug}.md`).

### Standalone visual eval

Evaluate layout and information architecture without a JD:

```bash
cold-read eval my-resume.pdf --prompt phase1-visual
```

### Options

```
cold-read eval --help          # Full option reference
cold-read eval --list-models   # Available models and their env vars
cold-read eval --model grok4   # Use a different model
cold-read eval -o result.md    # Custom output path
```

Results are saved to `cold-read-output/` by default.

## Prompt architecture

Prompts live in `prompts/` and are composed at runtime. JD-based evals stitch together:

1. **Preamble** (`preamble.md`) — recruiter persona, cold-application context, negativity bias framing
2. **Company dossier** (`--company`, optional) — what the company does, tech stack, culture, hiring bar
3. **Job description** (`--jd`) — the actual role requirements
4. **Task** (`task-jd-eval.md`) — rate each resume section a/b/c/d, identify gaps, make a decision

The vision pass uses `task-jd-vision.md` instead (eye-tracking simulation, squint test, recall test) and skips the company/JD entirely — it evaluates the document as a visual artifact.

Legacy standalone prompts (`phase1-visual.md`, `phase2-pm.md`, `phase2-swe.md`) are richer, self-contained evaluations written for a specific company context. They demonstrate more sophisticated prompt engineering but the composable JD-based system is more practical for general use.

## Calibration

The calibration system tests whether a vision model can accurately read a rendered document before trusting it to evaluate content. A frozen two-page resume image contains intentional traps:

- Fake identity elements (wrong name, nonsense email domain, international phone number for a US candidate)
- A footer name that doesn't match the header name
- A page counter showing "3" on page 2
- GitHub repo names with diacritical characters
- Small-point-size text that tests OCR resolution

18 questions test reading accuracy at three difficulty tiers. Models that can't read the traps reliably will produce evaluations that sound confident but are grounded in misreadings.

### Calibration results (February 2026)

| Model | Tier A (5) | Tier B (4) | Tier C (5) | Total /14 |
|-------|-----------|-----------|-----------|-----------|
| GPT-5.2 | 5 | 4 | 3.5 | **12.5** |
| Gemini (web only) | 5 | 4 | 3.5 | **12.5** |
| Claude Sonnet | 5 | 2 | 2 | 9 |
| Claude Opus | 4.5 | 1.5 | 2 | 8 |
| Grok 4 | 5 | 0 | 1.5 | 6.5 |

GPT-5.2 is the primary evaluation model. Gemini ties but has no programmatic API access.

## License

BSD-3-Clause. See [LICENSE](LICENSE).
