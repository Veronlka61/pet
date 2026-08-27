"""`peeksy.cli` — Typer facade for the `generate` / `test` / `report` commands.

Contract source: `peeksy/cli/CODEMANIFEST` (read-only). This cell owns no
capture or comparison logic: it loads the config and delegates to the runner.

Configuration errors surface through ONE shared handler (`_handle_config_errors`,
applied to all three command bodies) so a bad `--config` prints a human-readable
message instead of a Python traceback and exits 1. `test` additionally converts
the runner's exit code into `typer.Exit(code=...)` — never `sys.exit`, so pytest
can still intercept it.
"""

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

import typer
import yaml

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
        except subprocess.CalledProcessError as error:
            # allure ran and failed — surface ITS stderr, not a Python traceback.
            typer.echo(error.stderr.decode(errors="replace") or str(error), err=True)
            raise typer.Exit(code=1) from error


def main() -> None:
    """Run the Typer app — the `peeksy` console-script entry point."""
    app()


@contextmanager
def _handle_config_errors() -> Iterator[None]:
    """The ONE shared config-error handler: print human-readable, exit 1.

    Typer has no native global exception hook, so this context manager is
    applied inside all three command bodies rather than duplicated as three
    try/except blocks. `ValueError` covers pydantic's `ValidationError` and
    the loader's non-mapping-document error; `yaml.YAMLError` needs listing
    because parser errors (`ParserError` etc.) derive from it, not from
    `ValueError`. `typer.Exit` passes through untouched.
    """
    try:
        yield
    except (
        ValueError,
        yaml.YAMLError,
        FileNotFoundError,
        NotADirectoryError,
    ) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1) from error
