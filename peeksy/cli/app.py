"""`peeksy.cli` — Typer facade for the `generate` / `test` / `report` commands.

Contract source: `peeksy/cli/CODEMANIFEST` (read-only). This cell owns no
capture or comparison logic: it loads the config and delegates to the runner.

Configuration errors surface through ONE shared handler (`_handle_config_errors`,
applied to all three command bodies) so a bad `--config` prints a human-readable
message instead of a Python traceback and exits 1. `test` additionally converts
the runner's exit code into `typer.Exit(code=...)` — never `sys.exit`, so pytest
can still intercept it.
"""

from typing import Annotated, Self

import typer
import yaml
from pydantic import ValidationError

from peeksy.config import load_config
from peeksy.runner import run_generate, run_report, run_test

app = typer.Typer(help="Playwright visual regression: generate baselines, test, report.")

PASSED_SUMMARY = "all components passed"
FAILED_SUMMARY = "regression or infrastructure failure detected — see the Allure report"

ConfigOption = Annotated[str, typer.Option("--config", "-c", help="Suite file or site folder.")]
PageFilter = Annotated[
    list[str] | None,
    typer.Option("--page", help="Page name filter (repeatable)."),
]
ComponentFilter = Annotated[
    list[str] | None,
    typer.Option("--component", help="Component name filter (repeatable)."),
]


@app.command()
def generate(
    config: ConfigOption = "./peeksy.yml",
    page: PageFilter = None,
    component: ComponentFilter = None,
) -> None:
    """Capture and store baselines for the selected pages/components."""
    with _handle_config_errors():
        suite = load_config(config)
        run_generate(suite, page, component)


@app.command()
def test(
    config: ConfigOption = "./peeksy.yml",
    page: PageFilter = None,
    component: ComponentFilter = None,
) -> None:
    """Compare against baselines; exit non-zero on any regression."""
    with _handle_config_errors():
        suite = load_config(config)
        exit_code = run_test(suite, page, component)
    typer.echo(PASSED_SUMMARY if exit_code == 0 else FAILED_SUMMARY)
    raise typer.Exit(code=exit_code)


@app.command()
def report(config: ConfigOption = "./peeksy.yml") -> None:
    """Build the browsable Allure HTML report from the results directory."""
    with _handle_config_errors():
        suite = load_config(config)
        try:
            run_report(suite)
        except RuntimeError as error:  # missing `allure` CLI, per the reporting cell
            typer.echo(str(error), err=True)
            raise typer.Exit(code=1) from error


def main() -> None:
    """Run the Typer app — the `peeksy` console-script entry point."""
    app()


class _handle_config_errors:
    """The ONE shared config-error handler: print human-readable, exit 1.

    Typer has no native global exception hook, so this context manager is
    applied inside all three command bodies rather than duplicated as three
    try/except blocks.
    """

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_value, _traceback) -> bool:
        if exc_type is None or issubclass(exc_type, typer.Exit):
            return False
        if issubclass(
            exc_type, (ValidationError, yaml.YAMLError, FileNotFoundError, NotADirectoryError)
        ):
            typer.echo(f"error: {exc_value}", err=True)
            raise typer.Exit(code=1) from exc_value
        return False
