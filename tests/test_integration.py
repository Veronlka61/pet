"""Task 10 — end-to-end integration tests: generate → test → report (real Chromium).

Cross-cell verification of the design scenarios that need a real render: the
whole pipeline (config → capture → compare → reporting → cli) against local
`file://` fixture pages whose state mutates ON DISK between generate and test,
so the mutation survives `open_page` reloading the URL.

The fixture pages come from `tests/conftest.py::fixture_site`. Configs are real
site folders walked by `load_config` — nothing is stubbed except the `allure`
binary (a JDK dependency the plan declares optional).

Scenario source: `docs/design/peeksy-cli.md`, scenarios
`test_run_generate_then_test_passes`, `test_cli_test_exits_nonzero_on_regression`,
`test_regression_in_single_viewport_fails_only_that_result`,
`test_masked_dynamic_region_stable_and_no_mask_leakage`.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image
from typer.testing import CliRunner

from peeksy.cli import app
from peeksy.config import Suite, load_config
from peeksy.runner import run_generate, run_test
from tests.conftest import fixture_site

MASK_GRAY = (128, 128, 128, 255)  # #808080 — the exact overlay color
WIDE = {"width": 1280, "height": 720}
NARROW = {"width": 375, "height": 667}
SUITENAME = "demo-site"

# The design's regression scenario: `style="transform: translateY(2px)"` added
# to the header. `locator.screenshot()` crops by the element's TRANSFORMED box,
# so the shift is applied to the strip INSIDE the header — the visible ~2px
# regression the scenario is after (see conftest.fixture_site).
REGRESSION_STYLE = "transform: translateY(2px)"

runner = CliRunner()

# `peeksy.cli.app` (the Typer object) shadows the `peeksy.cli.app` submodule on
# the package, so string monkeypatch targets resolve to the wrong thing — grab
# the real module object instead.
app_module = sys.modules["peeksy.cli.app"]

PASSED_SUMMARY = "all components passed"
FAILED_SUMMARY = "regression or infrastructure failure detected — see the Allure report"


# --------------------------------------------------------------------------
# Site builders — real on-disk site folders walked by load_config
# --------------------------------------------------------------------------


def build_site(
    site_dir: Path,
    *,
    header_strip_style: str = "",
    media_shift: bool = False,
    randomize_timestamp: bool = False,
    with_footer: bool = False,
    viewports: list[dict] | None = None,
) -> Path:
    """Write a one-page site folder and return the `suite.yml` path.

    The page URL is the generated `index.html` (deterministic unless
    `randomize_timestamp` is set). Baselines/results/report live under the site
    folder, so every suite path is site-anchored as the loader requires.
    """
    html = fixture_site(
        site_dir / "pages" / "home",
        header_strip_style=header_strip_style,
        media_shift=media_shift,
        randomize_timestamp=randomize_timestamp,
    )
    (site_dir / "pages" / "home" / "header.yml").write_text(
        _component_yaml(viewports or [WIDE], masked=randomize_timestamp),
        encoding="utf-8",
    )
    if with_footer:
        (site_dir / "pages" / "home" / "footer.yml").write_text(
            _component_yaml(viewports or [WIDE], selector="#footer"),
            encoding="utf-8",
        )
    (site_dir / "pages" / "home" / "page.yml").write_text(
        f"url: {html.as_uri()}\n", encoding="utf-8"
    )

    suite_file = site_dir / "suite.yml"
    suite_file.write_text(
        "name: demo-site\n"
        "baseline_path: baselines\n"
        "results_path: allure-results\n"
        "report_path: allure-report\n"
        "threshold: 0.1\n"
        "tolerance: 0.5\n",
        encoding="utf-8",
    )
    return suite_file


def _component_yaml(
    viewports: list[dict], *, selector: str = "#header", masked: bool = False
) -> str:
    """One component document: selector, viewports, optional mask selectors."""
    # The selector is quoted: a bare `#header` is a YAML comment, not a value.
    lines = [f'selector: "{selector}"']
    if masked:
        lines.append("mask_selectors:")
        lines.append('  - ".timestamp"')
    lines.append("viewports:")
    for viewport in viewports:
        lines.append(f"  - width: {viewport['width']}")
        lines.append(f"    height: {viewport['height']}")
    return "\n".join(lines) + "\n"


def mutate_site(site_dir: Path, **changes: object) -> None:
    """Rewrite the fixture HTML on disk — the mutation must survive a reload."""
    fixture_site(site_dir / "pages" / "home", **changes)  # type: ignore[arg-type]


def read_results(results_dir: Path) -> list[dict]:
    """Parse every `*-result.json` in `results_dir` into a list of dicts."""
    files = sorted(results_dir.glob("*-result.json"))
    assert files, f"no *-result.json written into {results_dir}"
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def has_pixel(png_path: Path, rgba: tuple[int, int, int, int]) -> bool:
    """Whether any pixel of the PNG is exactly `rgba` (the mask-gray scan)."""
    needle = bytes(rgba)
    raw = Image.open(png_path).convert("RGBA").tobytes()
    return any(raw[i : i + 4] == needle for i in range(0, len(raw), 4))


def loaded(suite_file: Path) -> Suite:
    """`load_config` through the real loader — paths normalized against the site."""
    return load_config(str(suite_file))


# --------------------------------------------------------------------------
# Scenario 1 — generate then test passes
# --------------------------------------------------------------------------


def test_run_generate_then_test_passes(tmp_path: Path) -> None:
    suite_file = build_site(tmp_path / "site")

    run_generate(loaded(suite_file), None, None)
    exit_code = run_test(loaded(suite_file), None, None)

    assert exit_code == 0
    results = read_results(tmp_path / "site" / "allure-results")
    assert len(results) == 1
    assert results[0]["status"] == "passed"

    # Baseline lands at the run_policy path convention, page-namespaced.
    baseline = tmp_path / "site" / "baselines" / "home" / "header_1280x720.png"
    assert baseline.is_file(), f"baseline missing at {baseline}"
    current = tmp_path / "site" / "allure-results" / "home" / "header_1280x720.current.png"
    assert current.is_file(), "current capture missing"


# --------------------------------------------------------------------------
# Scenario 2 — a real on-disk regression exits non-zero through the CLI
# --------------------------------------------------------------------------


def test_cli_test_exits_nonzero_on_regression(tmp_path: Path) -> None:
    suite_file = build_site(tmp_path / "site")

    run_generate(loaded(suite_file), None, None)  # baseline from the ORIGINAL html

    # The mutation lives ON DISK, so it survives open_page reloading the URL.
    mutate_site(tmp_path / "site", header_strip_style=REGRESSION_STYLE)

    result = runner.invoke(app, ["test", "--config", str(suite_file)])

    assert result.exit_code == 1
    assert FAILED_SUMMARY in result.output

    (failed,) = read_results(tmp_path / "site" / "allure-results")
    assert failed["status"] == "failed"
    assert "mismatch" in failed["statusDetails"]["message"].lower()

    # The diff really was written and attached — the report shows what changed.
    diff = tmp_path / "site" / "allure-results" / "home" / "header_1280x720.diff.png"
    assert diff.is_file(), f"diff PNG missing at {diff}"
    attachment_sources = [a["source"] for a in failed["attachments"]]
    attachments = tmp_path / "site" / "allure-results"
    copied = [p for p in attachments.glob("*-attachment")]
    assert copied, "no attachment copied into the results dir"
    assert set(attachment_sources) == {p.name for p in copied}
    assert any(a["name"] == "diff" for a in failed["attachments"])


# --------------------------------------------------------------------------
# Scenario 3 — a viewport-scoped regression fails only that viewport's row
# --------------------------------------------------------------------------


def test_regression_in_single_viewport_fails_only_that_result(tmp_path: Path) -> None:
    suite_file = build_site(tmp_path / "site", viewports=[WIDE, NARROW])
    suite = loaded(suite_file)

    run_generate(suite, None, None)  # baselines for BOTH viewports

    # The shift applies ONLY inside the media query — wide stays clean.
    mutate_site(tmp_path / "site", media_shift=True)

    assert run_test(loaded(suite_file), None, None) == 1

    results = read_results(tmp_path / "site" / "allure-results")
    assert len(results) == 2
    by_status = {result["status"]: result for result in results}
    assert set(by_status) == {"passed", "failed"}

    # The baseline filenames are viewport-suffixed — no WxH collision.
    baselines = tmp_path / "site" / "baselines" / "home"
    assert (baselines / "header_1280x720.png").is_file()
    assert (baselines / "header_375x667.png").is_file()

    # Allure keeps one history row per (component, viewport).
    history_ids = {result["historyId"] for result in results}
    assert history_ids == {
        "peeksy::demo-site::home::header[1280x720]",
        "peeksy::demo-site::home::header[375x667]",
    }
    assert by_status["failed"]["historyId"] == "peeksy::demo-site::home::header[375x667]"


# --------------------------------------------------------------------------
# Scenario 4 — masking a dynamic region keeps it stable, without leaking
# --------------------------------------------------------------------------


def test_masked_dynamic_region_stable_and_no_mask_leakage(tmp_path: Path) -> None:
    suite_file = build_site(
        tmp_path / "site",
        randomize_timestamp=True,  # the timestamp re-randomizes on every load
        with_footer=True,
    )

    assert run_generate(loaded(suite_file), None, None) is None
    # Every open_page reload draws a NEW timestamp; the mask must hide it.
    assert run_test(loaded(suite_file), None, None) == 0

    results = read_results(tmp_path / "site" / "allure-results")
    assert {result["status"] for result in results} == {"passed"}

    # The masked overlay really covered the timestamp region…
    header = tmp_path / "site" / "allure-results" / "home" / "header_1280x720.current.png"
    assert has_pixel(header, MASK_GRAY), "mask overlay never appeared on the header"

    # …and never leaked onto the footer captured right after it.
    footer = tmp_path / "site" / "allure-results" / "home" / "footer_1280x720.current.png"
    assert footer.is_file()
    assert not has_pixel(footer, MASK_GRAY), "mask leaked onto the footer capture"


# --------------------------------------------------------------------------
# Edge — `peeksy report` end-to-end with allure stubbed + console script smoke
# --------------------------------------------------------------------------


class RunSpy:
    """Recording stub for `subprocess.run` — captures argv + kwargs per call."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append({"args": args, **kwargs})
        return subprocess.CompletedProcess(args, returncode=0)


def test_cli_report_end_to_end_with_allure_stubbed(tmp_path: Path, monkeypatch) -> None:
    suite_file = build_site(tmp_path / "site")
    run_generate(loaded(suite_file), None, None)
    assert run_test(loaded(suite_file), None, None) == 0

    spy = RunSpy()
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/allure")
    monkeypatch.setattr(subprocess, "run", spy)

    result = runner.invoke(app, ["report", "--config", str(suite_file)])

    assert result.exit_code == 0
    # Canonical argv: results dir positional FIRST, then --clean, -o report dir.
    assert len(spy.calls) == 1
    assert spy.calls[0]["args"] == [
        "allure",
        "generate",
        str(tmp_path / "site" / "allure-results"),
        "--clean",
        "-o",
        str(tmp_path / "site" / "allure-report"),
    ]
    assert spy.calls[0]["check"] is True
    assert spy.calls[0]["capture_output"] is True


def test_console_script_lists_all_three_commands() -> None:
    """`uv run peeksy --help` smoke — the packaged entry point works."""
    import os

    venv_bin = Path(sys.executable).parent / "peeksy"
    if not venv_bin.is_file():  # pragma: no cover — the console script always exists
        venv_bin = Path("/workspace/.venv/bin/peeksy")

    completed = subprocess.run(
        [str(venv_bin), "--help"],
        capture_output=True,
        text=True,
        env={**os.environ, "FONTCONFIG_FILE": os.environ.get("FONTCONFIG_FILE", "")},
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    for command in ("generate", "test", "report"):
        assert command in completed.stdout
