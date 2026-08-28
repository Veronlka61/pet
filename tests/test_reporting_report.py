"""Task 6 — contract + logic tests for `peeksy.reporting` stage 2 (`build_report`).

Contract source: `peeksy/reporting/CODEMANIFEST` (read-only). Routine
`build_report` lives at `report.py` and is importable from the
`peeksy.reporting` facade.

Everything here is stubbed — no JDK, no real `allure` binary. The tests pin
the two guarantees of the trace: a missing CLI raises a human-readable error
BEFORE any subprocess is spawned, and a present CLI is invoked exactly once
with the canonical argv (results dir positional first, `--clean`, `-o` report
dir) under `check=True, capture_output=True`. The argv order pinned here is
the plan's, which overrides the example snippet in
`.goga/usages/cooks/allure.md` (results dir last there).
"""

import inspect
import shutil
import subprocess

import pytest

import peeksy.reporting as reporting_facade
import peeksy.reporting.report as report_module
from peeksy.reporting import build_report

RESULTS_DIR = "/tmp/results"
REPORT_DIR = "/tmp/report"
CANONICAL_ARGV = ["allure", "generate", RESULTS_DIR, "--clean", "-o", REPORT_DIR]


class RunSpy:
    """Recording stub for `subprocess.run` — captures argv + kwargs per call."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._error = error

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append({"args": args, **kwargs})
        if self._error is not None:
            raise self._error
        return subprocess.CompletedProcess(args, returncode=0)


# --------------------------------------------------------------------------
# Contract tests — facade + signature
# --------------------------------------------------------------------------


def test_facade_exposes_build_report() -> None:
    exported = set(reporting_facade.__all__)
    assert "build_report" in exported
    assert callable(reporting_facade.build_report)
    assert reporting_facade.build_report.__module__ == "peeksy.reporting.report"


def test_build_report_signature_matches_contract() -> None:
    signature = inspect.signature(build_report)
    params = dict(signature.parameters)
    assert list(params) == ["results_dir", "report_dir"]
    assert all(p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for p in params.values())
    assert params["results_dir"].annotation is str
    assert params["report_dir"].annotation is str
    assert signature.return_annotation is None


# --------------------------------------------------------------------------
# Logic tests — missing CLI, canonical invocation, non-zero exit
# --------------------------------------------------------------------------


def test_build_report_missing_allure_raises_human_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = RunSpy()
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr(subprocess, "run", spy)

    with pytest.raises(RuntimeError) as excinfo:
        build_report(RESULTS_DIR, REPORT_DIR)

    message = str(excinfo.value).lower()
    # Install hint a human can act on: what is missing and how to get it.
    assert "allure" in message
    assert "brew" in message or "sdkman" in message
    assert "jdk" in message or "java" in message
    # The guard must fire BEFORE any subprocess spawn — never let subprocess
    # fail with FileNotFoundError instead.
    assert spy.calls == []


def test_build_report_invokes_allure_with_canonical_args(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = RunSpy()
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/allure")
    monkeypatch.setattr(subprocess, "run", spy)

    assert build_report(RESULTS_DIR, REPORT_DIR) is None

    assert len(spy.calls) == 1
    (call,) = spy.calls
    assert call["args"] == CANONICAL_ARGV  # results dir positional FIRST
    assert call["check"] is True
    assert call["capture_output"] is True
    # A wedged JVM must not hang `peeksy report` forever with its output
    # swallowed — every other external boundary carries an explicit bound.
    assert call["timeout"] == report_module._ALLURE_TIMEOUT_S


def test_build_report_timeout_raises_human_readable_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung allure process must surface as a readable error the CLI already
    knows how to handle (`RuntimeError`, same tier as the missing-CLI case),
    not a stalled command with no output."""
    spy = RunSpy(error=subprocess.TimeoutExpired(cmd=CANONICAL_ARGV, timeout=600, stderr=b""))
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/allure")
    monkeypatch.setattr(subprocess, "run", spy)

    with pytest.raises(RuntimeError, match="did not finish within"):
        build_report(RESULTS_DIR, REPORT_DIR)


def test_build_report_nonzero_exit_propagates_called_process_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = RunSpy(
        error=subprocess.CalledProcessError(
            returncode=1, cmd=CANONICAL_ARGV, stderr=b"allure: report generation failed"
        )
    )
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/allure")
    monkeypatch.setattr(subprocess, "run", spy)

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        build_report(RESULTS_DIR, REPORT_DIR)

    assert excinfo.value.returncode == 1
    # Captured stderr stays attached — the CLI surfaces it, not a bare code.
    assert b"report generation failed" in excinfo.value.stderr
    assert len(spy.calls) == 1
