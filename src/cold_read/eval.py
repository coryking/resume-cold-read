import base64
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI
from rich.console import Console
from rich.table import Table

load_dotenv()

console = Console()
MODELS: dict[str, dict] = {
    "gpt52": {
        "deployment": "gpt-52-chat",
        "api_key_env": "AZURE_PRIMARY_API_KEY",
        "endpoint_env": "AZURE_PRIMARY_ENDPOINT",
        "client_type": "azure_openai",
        "api_version": "2024-12-01-preview",
        "reasoning": True,
    },
    "grok4": {
        "deployment": "grok-4-fast-reasoning",
        "api_key_env": "AZURE_SECONDARY_API_KEY",
        "endpoint_env": "AZURE_SECONDARY_ENDPOINT",
        "client_type": "maas",
    },
    "claude-sonnet": {
        "deployment": "claude-sonnet-4-6",
        "client_type": "claude_cli",
        "model": "sonnet",
    },
    "claude-opus": {
        "deployment": "claude-opus-4-6",
        "client_type": "claude_cli",
        "model": "opus",
    },
}


def _get_project_root() -> Path:
    """Find cold-read project root by walking up to pyproject.toml, or COLD_READ_HOME."""
    env_home = os.environ.get("COLD_READ_HOME")
    if env_home:
        root = Path(env_home)
        if root.is_dir():
            return root

    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / "pyproject.toml").exists() and (current / "prompts").is_dir():
            return current
        current = current.parent

    raise RuntimeError(
        "Cannot find cold-read project root (looked for pyproject.toml + prompts/ directory). "
        "Set COLD_READ_HOME or run from the project directory."
    )


def _load_manifest() -> dict:
    """Load the prompts manifest."""
    root = _get_project_root()
    return json.loads((root / "prompts" / "manifest.json").read_text())


def _load_prompt(prompt_id: str) -> str:
    """Load a prompt file by phase ID from the manifest."""
    root = _get_project_root()
    manifest = _load_manifest()

    phase = next((p for p in manifest["phases"] if p["id"] == prompt_id), None)
    if phase is None:
        available = [p["id"] for p in manifest["phases"]]
        raise typer.BadParameter(
            f"Unknown prompt '{prompt_id}'. Available: {', '.join(available)}"
        )

    return (root / "prompts" / phase["prompt_file"]).read_text()


def _get_fixed_images(prompt_id: str) -> list[Path] | None:
    """Return fixed image paths for a phase, or None if it uses PDF rendering."""
    root = _get_project_root()
    manifest = _load_manifest()

    phase = next((p for p in manifest["phases"] if p["id"] == prompt_id), None)
    if phase is None or "fixed_images" not in phase:
        return None

    paths = []
    for img_rel in phase["fixed_images"]:
        img_path = root / img_rel
        if not img_path.exists():
            raise typer.BadParameter(f"Fixed calibration image not found: {img_path}")
        paths.append(img_path)
    return paths


def _get_all_prompt_ids() -> list[str]:
    """Return non-calibration prompt IDs from manifest. Calibration must be run explicitly."""
    manifest = _load_manifest()
    return [p["id"] for p in manifest["phases"] if p["id"] != "calibration"]


def _load_prompt_file(filename: str) -> str:
    """Load a prompt file by name from the prompts directory."""
    root = _get_project_root()
    return (root / "prompts" / filename).read_text()


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
        "## Screening Context\n\n" + _load_prompt_file("preamble.md"),
        "## Your Task\n\n" + _load_prompt_file("task-jd-vision.md"),
    ]
    return "\n\n".join(parts)


def _compose_jd_prompt(jd_path: Path, company_slug: str | None) -> tuple[str, str]:
    """Compose a JD-based eval prompt from parts. Returns (prompt_text, prompt_label)."""
    root = _get_project_root()
    parts: list[str] = []

    # Part 1: Preamble
    parts.append("## Screening Context\n\n" + _load_prompt_file("preamble.md"))

    # Part 2: Company dossier (optional)
    if company_slug:
        # Accept a file path or a slug
        company_path = Path(company_slug)
        if company_path.is_file():
            parts.append("## Company\n\n" + company_path.read_text())
        else:
            dossier_file = root / "prompts" / f"company-{company_slug}.md"
            if dossier_file.exists():
                parts.append("## Company\n\n" + dossier_file.read_text())
            else:
                console.print(
                    f"  [yellow]Warning:[/yellow] No company dossier found for '{company_slug}' "
                    f"(looked for {dossier_file} and file path). Skipping company context."
                )

    # Part 3: JD
    jd_text = jd_path.read_text()
    jd_stripped = _strip_jd_boilerplate(jd_text)
    parts.append("## Job Description\n\n" + jd_stripped)

    # Part 4: Task instructions
    parts.append("## Your Task\n\n" + _load_prompt_file("task-jd-eval.md"))

    prompt_label = "jd-eval"
    if company_slug:
        # Use filename stem for file paths, slug otherwise
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


def _encode_image(path: Path) -> str:
    """Base64-encode an image file."""
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def _build_client(model_config: dict) -> AzureOpenAI | OpenAI:
    """Build the appropriate OpenAI client for a model config."""
    key = os.environ.get(model_config["api_key_env"])
    endpoint = os.environ.get(model_config["endpoint_env"])

    if not key or not endpoint:
        missing = []
        if not key:
            missing.append(model_config["api_key_env"])
        if not endpoint:
            missing.append(model_config["endpoint_env"])
        raise typer.BadParameter(
            f"Missing env vars: {', '.join(missing)}. Check your .env file."
        )

    if model_config["client_type"] == "azure_openai":
        return AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=key,
            api_version=model_config["api_version"],
        )
    else:
        # MaaS (Llama, etc.)
        base_url = endpoint.rstrip("/") + "/openai/v1/"
        return OpenAI(base_url=base_url, api_key=key)


def _build_messages(
    prompt_text: str, image_pngs: list[Path], max_images: int | None = None
) -> list[dict]:
    """Build the chat messages with images as base64 content parts."""
    pages = image_pngs
    truncated = False
    if max_images and len(pages) > max_images:
        pages = pages[:max_images]
        truncated = True

    content_parts: list[dict] = []

    for png in pages:
        b64 = _encode_image(png)
        content_parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
            }
        )

    prompt_suffix = ""
    if truncated:
        prompt_suffix = (
            f"\n\n[NOTE: This model can only process {max_images} image(s). "
            f"You are seeing page(s) 1-{max_images} of {len(image_pngs)}.]"
        )

    content_parts.append({"type": "text", "text": prompt_text + prompt_suffix})

    return [{"role": "user", "content": content_parts}]


def _run_eval(
    model_name: str, model_config: dict, messages: list[dict]
) -> dict:
    """Run a single eval against one model. Returns response dict."""
    client = _build_client(model_config)
    deployment = model_config["deployment"]

    # GPT-5+ uses max_completion_tokens; older models and MaaS use max_tokens
    token_param = (
        "max_completion_tokens"
        if model_config.get("client_type") == "azure_openai"
        else "max_tokens"
    )
    extra_params: dict = {token_param: 16384}
    if model_config.get("reasoning"):
        extra_params["reasoning_effort"] = "high"

    response = client.chat.completions.create(
        model=deployment,
        messages=messages,
        **extra_params,
    )

    choice = response.choices[0]
    usage = response.usage

    return {
        "model": model_name,
        "deployment": deployment,
        "content": choice.message.content,
        "prompt_tokens": usage.prompt_tokens if usage else 0,
        "completion_tokens": usage.completion_tokens if usage else 0,
        "total_tokens": (usage.prompt_tokens + usage.completion_tokens) if usage else 0,
    }


def _run_eval_claude_cli(
    model_name: str, model_config: dict, prompt_text: str, image_pngs: list[Path]
) -> dict:
    """Run eval via Claude Code CLI in isolated mode. No API key needed."""
    model_alias = model_config["model"]

    # Build the user prompt: instruct Claude to read the images, then evaluate
    image_instructions = "\n".join(
        f"- Page {i+1}: {png.resolve()}" for i, png in enumerate(image_pngs)
    )
    user_prompt = (
        f"Read each of the following resume page images using the Read tool, "
        f"then follow the evaluation instructions in your system prompt.\n\n"
        f"{image_instructions}"
    )

    cmd = [
        "claude",
        "-p",
        "--model", model_alias,
        "--tools", "Read",
        "--setting-sources", "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--dangerously-skip-permissions",
        "--system-prompt", prompt_text,
        "--output-format", "json",
        user_prompt,
    ]

    # Strip CLAUDECODE env var so the CLI doesn't refuse to run inside our session
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=tempfile.gettempdir(),
        env=env,
        timeout=300,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"claude CLI exited with code {result.returncode}: {result.stderr.strip()}"
        )

    # Parse JSON output for the response content
    try:
        output = json.loads(result.stdout)
        content = output.get("result", result.stdout)
    except json.JSONDecodeError:
        # Fall back to raw text if JSON parsing fails
        content = result.stdout.strip()

    return {
        "model": model_name,
        "deployment": model_config["deployment"],
        "content": content,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def _save_result(
    model_name: str, prompt_id: str, content: str, pdf_name: str
) -> Path:
    """Save eval result to cold-read-output/."""
    evals_dir = Path("cold-read-output")
    evals_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{model_name}-{prompt_id}-{timestamp}.md"
    out_path = evals_dir / filename

    header = f"# Eval: {model_name} / {prompt_id}\n\n"
    header += f"**PDF:** {pdf_name}  \n"
    header += f"**Date:** {datetime.now().isoformat()}  \n"
    header += f"**Model:** {model_name} ({MODELS[model_name]['deployment']})\n\n---\n\n"

    out_path.write_text(header + content)
    return out_path


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
        table.add_column("Type")
        table.add_column("API Key Env")

        for name, config in MODELS.items():
            table.add_row(
                name,
                config["deployment"],
                config["client_type"],
                config.get("api_key_env", "—"),
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
            prompt_ids = _get_all_prompt_ids()
        else:
            prompt_ids = [prompt]

    # Check if all phases use fixed images (PDF not needed)
    # In JD mode, we always need the PDF
    all_fixed = not jd_mode and all(_get_fixed_images(pid) is not None for pid in prompt_ids)

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

    # Auto-generate output path if not specified
    if output is None:
        evals_dir = Path("cold-read-output")
        evals_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        pdf_stem = pdf.stem if pdf else "calibration"
        ext = ".json" if output_json else ".md"
        output = evals_dir / f"{pdf_stem}-{timestamp}{ext}"

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
            phase_pngs = _get_fixed_images(prompt_id) or pngs

        for model_name in model_names:
            eval_num += 1
            model_config = MODELS[model_name]
            max_imgs = model_config.get("max_images")
            messages = _build_messages(prompt_text, phase_pngs, max_images=max_imgs)
            deployment = model_config["deployment"]
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
                if model_config["client_type"] == "claude_cli":
                    result = _run_eval_claude_cli(
                        model_name, model_config, prompt_text, phase_pngs
                    )
                else:
                    result = _run_eval(model_name, model_config, messages)
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

            # Save individual file
            pdf_label = pdf.name if pdf else "calibration-resume"
            out_path = _save_result(model_name, prompt_id, result["content"], pdf_label)
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
