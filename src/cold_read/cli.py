import typer

from cold_read import config as _config

app = typer.Typer(help="Resume Cold Reader — evaluate resumes with vision models.")


@app.callback()
def main() -> None:
    """Resume Cold Reader — evaluate resumes with vision models."""
    # Load the bucket-2 .env layers once, before any subcommand runs.
    _config.load_env()


def register_commands() -> None:
    from cold_read.eval import eval_command

    app.command(name="eval", help="Run LLM evals against a resume PDF.")(eval_command)


register_commands()
