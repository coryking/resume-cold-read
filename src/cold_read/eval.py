import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from cold_read import config as _config
from cold_read import output as _output
from cold_read import prompts as _prompts
from cold_read.providers import SHAPES
from cold_read.providers.shape import CredentialsMissingError, EvalResult

console = Console()

# Model registry. Each entry names a provider shape plus per-alias extras
# that the shape consumes via its `run()` / `credential_test()` `extras`
# dict. Unit 6 of the install-story plan moves `deployment` out of here
# and into user-owned config.toml; for now it stays as a maintainer-shipped
# default so the four currently-registered models keep working.
MODELS: dict[str, dict] = {
    "gpt52": {
        "shape": "azure-openai",
        "deployment": "gpt-52-chat",
        "api_version": "2024-12-01-preview",
        "reasoning": True,
    },
    "grok4": {
        "shape": "azure-maas",
        "deployment": "grok-4-fast-reasoning",
    },
    "claude-sonnet": {
        "shape": "claude-cli",
        "claude_alias": "sonnet",
        "deployment": "claude-sonnet-4-6",
    },
    "claude-opus": {
        "shape": "claude-cli",
        "claude_alias": "opus",
        "deployment": "claude-opus-4-6",
    },
}


def _load_prompt(prompt_id: str) -> str:
    """Load a prompt file by phase ID, re-raising as typer.BadParameter for CLI UX."""
    try:
        return _prompts.load_prompt(prompt_id)
    except _prompts.UnknownPromptError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _strip_jd_boilerplate(jd_text: str) -> str:
    """Strip the ## Essentials metadata block from saved JD files.

    Only removes the frontmatter metadata (job ID, URL, salary, dates) that
    ATS tools add. EEO statements, benefits, and other boilerplate are left
    in — the model is prompted to ignore them.
    """
    lines = jd_text.split("\n")
    result_lines: list[str] = []
    in_essentials = False

    for line in lines:
        if re.match(r"^##\s+Essentials\b", line, re.IGNORECASE):
            in_essentials = True
            continue
        if in_essentials:
            if re.match(r"^##\s+", line) and not re.match(r"^##\s+Essentials\b", line, re.IGNORECASE):
                in_essentials = False
            else:
                continue

        result_lines.append(line)

    return "\n".join(result_lines).strip()


def _compose_vision_prompt() -> str:
    """Compose the vision pass prompt (preamble + vision task). No JD, no company."""
    parts = [
        "## Screening Context\n\n" + _prompts.load_prompt_file("preamble.md"),
        "## Your Task\n\n" + _prompts.load_prompt_file("task-jd-vision.md"),
    ]
    return "\n\n".join(parts)


def _compose_jd_prompt(jd_path: Path, company_slug: str | None) -> tuple[str, str]:
    """Compose a JD-based eval prompt from parts. Returns (prompt_text, prompt_label)."""
    parts: list[str] = []

    # Part 1: Preamble
    parts.append("## Screening Context\n\n" + _prompts.load_prompt_file("preamble.md"))

    # Part 2: Company dossier (optional). `_config.resolve_company` accepts
    # either a file path or a slug rooted in the user config dir and never
    # falls back to packaged bucket-1 prompts.
    if company_slug:
        dossier = _config.resolve_company(company_slug)
        if dossier is not None:
            parts.append("## Company\n\n" + dossier.read_text())
        else:
            console.print(
                f"  [yellow]Warning:[/yellow] No company dossier found for '{company_slug}'. "
                f"Pass a file path or create `{_config.companies_dir() / (company_slug + '.md')}`."
            )

    # Part 3: JD
    jd_text = jd_path.read_text()
    jd_stripped = _strip_jd_boilerplate(jd_text)
    parts.append("## Job Description\n\n" + jd_stripped)

    # Part 4: Task instructions
    parts.append("## Your Task\n\n" + _prompts.load_prompt_file("task-jd-eval.md"))

    prompt_label = "jd-eval"
    if company_slug:
        company_path = Path(company_slug)
        if company_path.is_file():
            prompt_label = f"jd-eval-{company_path.stem}"
        else:
            prompt_label = f"jd-eval-{company_slug}"

    return "\n\n".join(parts), prompt_label


def _pdf_to_pngs(pdf_path: Path) -> list[Path]:
    """Convert PDF to PNG pages using pdftoppm. Returns list of PNG paths."""
    tmp_dir = tempfile.mkdtemp(prefix="cold-read-")
    prefix = Path(tmp_dir) / "page"

    result = subprocess.run(
        ["pdftoppm", "-png", "-r", "150", str(pdf_path), str(prefix)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise typer.Exit(f"pdftoppm failed: {result.stderr}")

    pngs = sorted(Path(tmp_dir).glob("page-*.png"))
    if not pngs:
        raise typer.Exit("pdftoppm produced no output files.")

    return pngs


def _run_model_eval(model_name: str, prompt_text: str, image_pngs: list[Path]) -> dict:
    """Resolve the shape for `model_name` and invoke it.

    Returns the legacy dict shape the output loop expects. Once the rest
    of the pipeline speaks in `EvalResult` we can drop the translation.
    """
    model_config = MODELS[model_name]
    shape_name = model_config["shape"]
    shape = SHAPES[shape_name]

    extras = {k: v for k, v in model_config.items() if k != "shape"}
    eval_result: EvalResult = shape.run(prompt_text, image_pngs, extras)

    return {
        "model": model_name,
        "deployment": model_config.get("deployment", ""),
        "content": eval_result.content,
        "prompt_tokens": eval_result.prompt_tokens,
        "completion_tokens": eval_result.completion_tokens,
        "total_tokens": eval_result.total_tokens,
    }


def eval_command(
    pdf: Annotated[
        Path | None,
        typer.Argument(help="Path to resume PDF to evaluate."),
    ] = None,
    prompt: Annotated[
        str,
        typer.Option(help="Prompt phase to run: phase1-visual, phase2-pm, phase2-swe, or 'all'."),
    ] = "phase1-visual",
    model: Annotated[
        str,
        typer.Option(help="Model to use."),
    ] = "gpt52",
    jd: Annotated[
        Path | None,
        typer.Option("--jd", help="Path to a job description file. Enables JD-based eval (composable prompt)."),
    ] = None,
    company: Annotated[
        str | None,
        typer.Option("--company", help="Company slug or path to dossier file. Used with --jd."),
    ] = None,
    list_models: Annotated[
        bool,
        typer.Option("--list-models", help="Show available models and exit."),
    ] = False,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output results as JSON."),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write combined results to this file (markdown or JSON)."),
    ] = None,
) -> None:
    """Run LLM evals against a resume PDF."""
    if list_models:
        table = Table(title="Available Models")
        table.add_column("Name", style="bold")
        table.add_column("Deployment")
        table.add_column("Shape")
        table.add_column("Env Vars")

        for name, cfg in MODELS.items():
            shape = SHAPES[cfg["shape"]]
            env_vars = ", ".join(f.name for f in shape.credential_fields) or "—"
            table.add_row(
                name,
                cfg.get("deployment", "—"),
                shape.name,
                env_vars,
            )

        console.print(table)
        raise typer.Exit()

    # Validate --jd flag
    jd_mode = jd is not None
    if jd_mode:
        if not jd.exists():
            console.print(f"[red]Error:[/red] JD file not found: {jd}")
            raise typer.Exit(1)
        if pdf is None:
            console.print("[red]Error:[/red] PDF argument is required with --jd.")
            raise typer.Exit(1)

    if company and not jd_mode:
        console.print("[yellow]Warning:[/yellow] --company is ignored without --jd.")

    if jd_mode:
        # Two-pass JD eval: vision first, then content
        vision_prompt = _compose_vision_prompt()
        content_prompt, content_label = _compose_jd_prompt(jd, company)
        jd_pass_prompts = {
            "jd-vision": vision_prompt,
            content_label: content_prompt,
        }
        prompt_ids = list(jd_pass_prompts.keys())
    else:
        # Legacy phase-based eval
        if prompt == "all":
            prompt_ids = _prompts.get_all_prompt_ids()
        else:
            prompt_ids = [prompt]

    # Check if all phases use fixed images (PDF not needed)
    # In JD mode, we always need the PDF
    all_fixed = not jd_mode and all(
        _prompts.get_fixed_images(pid) is not None for pid in prompt_ids
    )

    if pdf is None and not all_fixed:
        console.print("[red]Error:[/red] PDF argument is required for non-calibration prompts.")
        raise typer.Exit(1)

    if pdf is not None and not pdf.exists():
        console.print(f"[red]Error:[/red] File not found: {pdf}")
        raise typer.Exit(1)

    # Determine which models to run
    if model not in MODELS:
        console.print(f"[red]Error:[/red] Unknown model '{model}'. Use --list-models to see available.")
        raise typer.Exit(1)
    model_names = [model]

    # Convert PDF to PNGs (only if needed)
    pngs: list[Path] = []
    if pdf is not None and not all_fixed:
        console.print(f"[dim]Converting {pdf.name} to images (150 DPI)...[/dim]")
        pngs = _pdf_to_pngs(pdf)
        console.print(f"  {len(pngs)} page(s) ready.\n")

    # Auto-generate output path if not specified. Goes under the user data
    # dir's runs/ subtree — never CWD — so the command is safe to run from
    # any directory.
    if output is None:
        pdf_stem = pdf.stem if pdf else "calibration"
        ext = ".json" if output_json else ".md"
        output = _output.default_output_path(pdf_stem, ext=ext)

    # Plan summary
    console.print(f"[bold]Plan:[/bold] {len(prompt_ids)} prompt(s) x {len(model_names)} model(s) = {len(prompt_ids) * len(model_names)} eval(s)")
    if jd_mode:
        console.print(f"  Mode:    JD-based eval (vision + content)")
        console.print(f"  JD:      {jd}")
        if company:
            console.print(f"  Company: {company}")
    else:
        console.print(f"  Prompts: {', '.join(prompt_ids)}")
    console.print(f"  Models:  {', '.join(model_names)}")
    console.print(f"  Output:  {output}\n")

    # Run evals
    all_results: list[dict] = []
    eval_num = 0
    total_evals = len(prompt_ids) * len(model_names)

    for prompt_id in prompt_ids:
        if jd_mode:
            prompt_text = jd_pass_prompts[prompt_id]
            phase_pngs = pngs
        else:
            prompt_text = _load_prompt(prompt_id)
            # Use fixed images if available, otherwise PDF-rendered PNGs
            phase_pngs = _prompts.get_fixed_images(prompt_id) or pngs

        for model_name in model_names:
            eval_num += 1
            model_config = MODELS[model_name]
            max_imgs = model_config.get("max_images")
            deployment = model_config.get("deployment", "")
            reasoning = "reasoning" if model_config.get("reasoning") else "standard"

            console.rule(f"[bold]({eval_num}/{total_evals}) {model_name} / {prompt_id}[/bold]")

            if max_imgs and len(phase_pngs) > max_imgs:
                console.print(
                    f"  [yellow]Sending page 1 only "
                    f"({max_imgs}/{len(phase_pngs)} pages)[/yellow]"
                )

            console.print(f"  [dim]Deployment:[/dim] {deployment}")
            console.print(f"  [dim]Mode:[/dim]       {reasoning}")
            console.print(f"  [dim]Images:[/dim]     {min(len(phase_pngs), max_imgs or len(phase_pngs))} page(s)")
            console.print(f"  [dim]Calling API...[/dim]")

            try:
                result = _run_model_eval(model_name, prompt_text, phase_pngs)
            except CredentialsMissingError as e:
                console.print(f"  FAILED: {e}\n", highlight=False)
                continue
            except Exception as e:
                console.print(f"  FAILED: {type(e).__name__}: {e}\n", highlight=False)
                continue

            token_str = ""
            if result["total_tokens"] > 0:
                token_str = f" ({result['total_tokens']} tokens: {result['prompt_tokens']} in / {result['completion_tokens']} out)"
            console.print(f"  Done.{token_str}\n", highlight=False)

            result["prompt_id"] = prompt_id
            all_results.append(result)

            if not output_json:
                # Plain text output — no Rich panels
                console.print(f"--- {model_name} / {prompt_id} ---\n", highlight=False)
                console.print(result["content"], highlight=False)
                console.print("", highlight=False)

            # Save individual file under the runs dir
            pdf_label = pdf.name if pdf else "calibration-resume"
            out_path = _output.save_individual(
                model_name=model_name,
                deployment=deployment,
                prompt_id=prompt_id,
                content=result["content"],
                pdf_name=pdf_label,
            )
            console.print(f"  Saved: {out_path}\n", highlight=False)

    # Write combined output file
    if all_results:
        if output_json:
            output.write_text(json.dumps(all_results, indent=2))
        else:
            parts = []
            for r in all_results:
                parts.append(f"# {r['model']} / {r['prompt_id']}\n\n{r['content']}")
            output.write_text("\n\n---\n\n".join(parts))

        console.print(f"Combined results written to {output}", highlight=False)

    # Token summary (compact)
    if all_results and not output_json:
        console.print("\nToken usage:", highlight=False)
        for r in all_results:
            if r["total_tokens"] > 0:
                console.print(f"  {r['model']}/{r['prompt_id']}: {r['prompt_tokens']} in / {r['completion_tokens']} out / {r['total_tokens']} total", highlight=False)
