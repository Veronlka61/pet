"""Task 9 — contract + logic tests for `peeksy.cli` (generate/test/report/main).

Contract source: `peeksy/cli/CODEMANIFEST` (read-only). The four routines live
at `app.py` and are importable from the `peeksy.cli` facade, alongside the
module-level Typer `app`.

Contract tests come first (TDD): facade exposure, the module-level `app`, and
`main()` being callable.

Logic tests use `typer.testing.CliRunner` with `run_generate`/`run_test`/
`run_report` and `load_config` stubbed via monkeypatch on
`peeksy.cli.app` — no browser, no allure binary. They pin the option surface
(repeatable `--page`/`--component`, `--config/-c` default `./peeksy.yml`), the
exit-code policy for `test`, the ONE shared config-error handler, and the
missing-allure install hint for `report`.
"""

import inspect
import sys
import types
from pathlib import Path
from typing import get_args, get_origin

import pytest
import yaml
from typer.testing import CliRunner

import peeksy.cli as cli_facade
from peeksy.cli import app, generate, main, report
from peeksy.config import Suite

# `peeksy.cli.app` (the Typer object) shadows the `peeksy.cli.app` submodule on
# the package, so string monkeypatch targets resolve to the wrong thing — patch
# the real module object instead. The `test` command is reached through it too:
# a module-level binding named `test*` would be collected by pytest as a test.
app_module = sys.modules["peeksy.cli.app"]
__test_command = app_module.test

PASSED_SUMMARY = "all components passed"
FAILED_SUMMARY = "regression or infrastructure failure detected — see the Allure report"

runner = CliRunner()

# --------------------------------------------------------------------------
# Contract tests — facade, module-level app, main()
# --------------------------------------------------------------------------


def test_facade_exports_the_cli_surface() -> None:
    assert cli_facade.__all__ == ["app", "generate", "main", "report", "test"]
    for name in cli_facade.__all__:
        assert hasattr(cli_facade, name), name
    assert cli_facade.generate.__module__ == "peeksy.cli.app"
    assert cli_facade.test.__module__ == "peeksy.cli.app"
    assert cli_facade.report.__module__ == "peeksy.cli.app"
    assert cli_facade.main.__module__ == "peeksy.cli.app"


def test_module_level_typer_app_exists() -> None:
    assert callable(app)
    assert app.__class__.__name__ == "Typer"
    assert len(app.registered_commands) == 3


def test_main_is_callable() -> None:
    assert callable(main)
    assert inspect.signature(main).parameters == {}


def test_command_signatures_match_contract() -> None:
    for command in (generate, __test_command, report):
        params = dict(inspect.signature(command).parameters)
        expected = ["config"] if command is report else ["config", "page", "component"]
        assert list(params) == expected, command.__name__

    # Declared types: `str` config, `list[str] | None` filters, under Annotated.
    for command in (generate, __test_command):
        params = dict(inspect.signature(command).parameters)
        assert get_args(params["config"].annotation)[0] is str
        page_annotation = get_args(params["page"].annotation)[0]
        page_types = (
            get_args(page_annotation)
            if get_origin(page_annotation) is types.UnionType
            else (page_annotation,)
        )
        assert list in page_types or list[str] in page_types
        assert type(None) in page_types
    report_config = dict(inspect.signature(report).parameters)["config"].annotation
    assert get_args(report_config)[0] is str


def test_app_lists_the_three_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("generate", "test", "report"):
        assert command in result.output


# --------------------------------------------------------------------------
# Stubs — the runner and config loader are never real here
# --------------------------------------------------------------------------


class Recorder:
    """Collects every delegated call so tests can assert on the hand-off."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def as_generate(
        self, suite: Suite, pages: list[str] | None, components: list[str] | None
    ) -> None:
        self.calls.append(
            {"fn": "generate", "suite": suite, "pages": pages, "components": components}
        )

    def as_test(self, suite: Suite, pages: list[str] | None, components: list[str] | None) -> int:
        self.calls.append({"fn": "test", "suite": suite, "pages": pages, "components": components})
        return self.exit_code

    def as_report(self, suite: Suite) -> None:
        self.calls.append({"fn": "report", "suite": suite})

    exit_code: int = 0


@pytest.fixture
def stubbed_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Recorder:
    """Stub `load_config` + the three `run_*` routines on the cli module."""
    recorder = Recorder()
    recorder.exit_code = 0
    suite = Suite(
        name="demo-site",
        pages=[],
        baseline_path=str(tmp_path / "baseline"),
        results_path=str(tmp_path / "results"),
        report_path=str(tmp_path / "report"),
        threshold=0.1,
        tolerance=0.5,
    )
    monkeypatch.setattr(app_module, "load_config", lambda _path: suite)
    monkeypatch.setattr(app_module, "run_generate", recorder.as_generate)
    monkeypatch.setattr(app_module, "run_test", recorder.as_test)
    monkeypatch.setattr(app_module, "run_report", recorder.as_report)
    return recorder


def test_generate_delegates_and_exits_zero(stubbed_runner: Recorder) -> None:
    result = runner.invoke(app, ["generate"])

    assert result.exit_code == 0
    (call,) = stubbed_runner.calls
    assert call["fn"] == "generate"
    assert call["pages"] is None
    assert call["components"] is None


def test_repeatable_page_and_component_filters_are_forwarded(stubbed_runner: Recorder) -> None:
    result = runner.invoke(
        app,
        [
            "generate",
            "--page",
            "home",
            "--page",
            "about",
            "--component",
            "header",
            "--component",
            "sidebar",
        ],
    )

    assert result.exit_code == 0
    (call,) = stubbed_runner.calls
    assert call["pages"] == ["home", "about"]
    assert call["components"] == ["header", "sidebar"]


def test_config_default_is_project_root_suite_file(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_load(path: str) -> Suite:
        seen.append(path)
        return _suite()

    monkeypatch.setattr(app_module, "load_config", fake_load)
    result = runner.invoke(app, ["generate"])

    assert result.exit_code == 0
    assert seen == ["./peeksy.yml"]


def test_config_short_flag_and_explicit_value_are_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def fake_load(path: str) -> Suite:
        seen.append(path)
        return _suite()

    monkeypatch.setattr(app_module, "load_config", fake_load)
    assert runner.invoke(app, ["generate", "-c", "sites/example.com"]).exit_code == 0
    assert seen == ["sites/example.com"]
    assert runner.invoke(app, ["test", "--config", "other.yml"]).exit_code == 0
    assert seen == ["sites/example.com", "other.yml"]


def test_test_exit_code_propagates_and_summary_is_printed(stubbed_runner: Recorder) -> None:
    stubbed_runner.exit_code = 1
    failing = runner.invoke(app, ["test"])

    assert failing.exit_code == 1
    assert FAILED_SUMMARY in failing.output
    assert PASSED_SUMMARY not in failing.output
    assert stubbed_runner.calls[-1]["fn"] == "test"

    stubbed_runner.exit_code = 0
    passing = runner.invoke(app, ["test"])

    assert passing.exit_code == 0
    assert PASSED_SUMMARY in passing.output
    assert FAILED_SUMMARY not in passing.output


def test_report_delegates_to_run_report(stubbed_runner: Recorder) -> None:
    result = runner.invoke(app, ["report"])

    assert result.exit_code == 0
    (call,) = stubbed_runner.calls
    assert call["fn"] == "report"


def test_report_prints_install_hint_when_allure_absent(
    stubbed_runner: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing_allure(_suite: Suite) -> None:
        raise RuntimeError(
            "allure CLI not found on PATH. Install it (e.g. `brew install allure` "
            "or via sdkman) — it requires a JDK."
        )

    monkeypatch.setattr(app_module, "run_report", missing_allure)
    result = runner.invoke(app, ["report"])

    assert result.exit_code == 1
    assert "allure" in result.output.lower()
    assert "Traceback (most recent call last)" not in result.output


# --------------------------------------------------------------------------
# App-level config-error handler — ONE handler, all three commands
# --------------------------------------------------------------------------


def _suite() -> Suite:
    """A minimal valid `Suite` for the stubbed loader."""
    return Suite(
        name="demo-site",
        pages=[],
        baseline_path="/tmp/baseline",
        results_path="/tmp/results",
        report_path="/tmp/report",
        threshold=0.1,
        tolerance=0.5,
    )


def _write_site(tmp_path: Path, *, threshold: object = 0.1, tolerance: object = 0.5) -> Path:
    """Write a valid suite file; callers corrupt it per scenario."""
    suite_file = tmp_path / "suite.yml"
    suite_file.write_text(
        yaml.safe_dump(
            {
                "name": "demo-site",
                "baseline_path": str(tmp_path / "baseline"),
                "results_path": str(tmp_path / "results"),
                "report_path": str(tmp_path / "report"),
                "threshold": threshold,
                "tolerance": tolerance,
            }
        ),
        encoding="utf-8",
    )
    return suite_file


@pytest.mark.parametrize("command", ["generate", "test", "report"])
def test_invalid_config_is_human_readable_without_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str
) -> None:
    """A range violation reaches Pydantic -> the shared handler prints + exits 1."""
    suite_file = _write_site(tmp_path, threshold=5)  # threshold must be (0..1)

    result = runner.invoke(app, [command, "--config", str(suite_file)])

    assert result.exit_code == 1
    # The error was HANDLED, not raised: only the exit exception may remain.
    assert result.exception is None or isinstance(result.exception, SystemExit)
    # The offending field is named, so the user knows what to fix.
    assert "threshold" in result.output


@pytest.mark.parametrize("command", ["generate", "test", "report"])
def test_broken_yaml_is_human_readable_without_traceback(tmp_path: Path, command: str) -> None:
    """Syntactically broken YAML never reaches Pydantic — `yaml.YAMLError` path."""
    suite_file = tmp_path / "suite.yml"
    suite_file.write_text("name: [unclosed\n  broken: {{{\n", encoding="utf-8")

    result = runner.invoke(app, [command, "--config", str(suite_file)])

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.output.startswith("error:")


@pytest.mark.parametrize(
    ("content", "label"),
    [("", "empty"), ("- just\n- a\n- list\n", "a YAML list"), ("42\n", "a bare scalar")],
)
@pytest.mark.parametrize("command", ["generate", "test", "report"])
def test_non_mapping_config_is_human_readable_without_traceback(
    tmp_path: Path, command: str, content: str, label: str
) -> None:
    """A non-mapping document raises the loader's `ValueError` — handled, no traceback."""
    suite_file = tmp_path / "suite.yml"
    suite_file.write_text(content, encoding="utf-8")

    result = runner.invoke(app, [command, "--config", str(suite_file)])

    # Regression: `ValueError` is not a `ValidationError` — an unhandled raise
    # here would surface as result.exception with empty output.
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.output.startswith("error:")
    assert "suite.yml" in result.output


@pytest.mark.parametrize("command", ["generate", "test", "report"])
def test_missing_config_path_is_human_readable_without_traceback(
    tmp_path: Path, command: str
) -> None:
    result = runner.invoke(app, [command, "--config", str(tmp_path / "nope.yml")])

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    # The path is named so the message is actionable.
    assert "nope.yml" in result.output


def test_report_surfaces_allure_stderr_on_cli_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """allure exiting non-zero must print ITS stderr, not a Python traceback."""
    import subprocess as subprocess_module

    suite_file = _write_site(tmp_path)

    def failing_run(*_args: object, **_kwargs: object) -> None:
        raise subprocess_module.CalledProcessError(
            returncode=1, cmd=["allure", "generate"], stderr=b"allure: no results found"
        )

    # allure "is installed" (the which check passes) but its run fails.
    monkeypatch.setattr("peeksy.reporting.report.shutil.which", lambda _name: "/usr/bin/allure")
    monkeypatch.setattr("peeksy.reporting.report.subprocess.run", failing_run)
    result = runner.invoke(app, ["report", "--config", str(suite_file)])

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "allure: no results found" in result.output


def test_single_handler_is_shared_not_duplicated() -> None:
    """The contract wants ONE config-error handler applied to all three bodies — no copy-paste.

    Counts only handlers naming `ValueError` (the config-error family's common
    base); the `report` command's separate `CalledProcessError` handler for
    allure stderr is a different concern and must not be counted.
    """
    import ast

    source = inspect.getsource(__import__("peeksy.cli.app", fromlist=["app"]))
    tree = ast.parse(source)
    config_errors = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler) and "ValueError" in ast.unparse(node.type)
    ]
    assert len(config_errors) == 1
