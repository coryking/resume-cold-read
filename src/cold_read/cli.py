import functools
from typing import Callable

import typer
from rich.console import Console

from cold_read import config as _config
from cold_read.errors import ColdReadError, format_error

_err_console = Console(stderr=True)

app = typer.Typer(help="Resume Cold Reader — evaluate resumes with vision models.")


@app.callback()
def main() -> None:
    """Resume Cold Reader — evaluate resumes with vision models."""
    # Load the bucket-2 .env layers once, before any subcommand runs.
    _config.load_env()


def _with_error_formatting(fn: Callable) -> Callable:
    """Catch ColdReadError, print a bucket-labeled message, exit cleanly.

    Keeps every command from having to repeat the same try/except and
    from cluttering stderr with Python tracebacks for errors we know
    how to describe.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ColdReadError as exc:
            line = format_error(exc)
            _err_console.print(
                f"[bold red]\\[{line.label}][/bold red] {line.message}"
            )
            if line.suggestion:
                _err_console.print(f"  {line.suggestion}")
            raise typer.Exit(exc.exit_code) from exc

    return wrapper


def register_commands() -> None:
    from cold_read.doctor import doctor_command
    from cold_read.eval import eval_command
    from cold_read.wizard import init_command

    app.command(name="eval", help="Run LLM evals against a resume PDF.")(
        _with_error_formatting(eval_command)
    )
    app.command(
        name="init",
        help="Interactive wizard: configure providers and default model.",
    )(_with_error_formatting(init_command))
    app.command(
        name="doctor",
        help="Report on install + config + provider + model status.",
    )(_with_error_formatting(doctor_command))


register_commands()
