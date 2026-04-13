import typer

app = typer.Typer(help="Resume Cold Reader — evaluate resumes with vision models.")


@app.callback()
def main() -> None:
    """Resume Cold Reader — evaluate resumes with vision models."""


def register_commands() -> None:
    from cold_read.eval import eval_command

    app.command(name="eval", help="Run LLM evals against a resume PDF.")(eval_command)


register_commands()
