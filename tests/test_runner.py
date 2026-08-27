"""Task 8 — contract + logic tests for `peeksy.runner` (run_generate/run_test/run_report).

Contract source: `peeksy/runner/CODEMANIFEST` (read-only). The three routines
live at `runner.py` and are importable from the `peeksy.runner` facade.

Contract tests come first (TDD): facade exposure, the three signatures
(`run_test` returns `int`), and the boundary rule that no Playwright import
leaks into this cell.

Logic tests run against a `FakeCaptureSession` monkeypatched over
`peeksy.runner.runner.CaptureSession` — its `capture_component` writes a small
PIL-generated PNG, and `open_page` raises on demand. `Suite` objects are built
directly; no browser is involved at this level.
"""

import inspect
import json
from pathlib import Path
from typing import ClassVar

from PIL import Image

import peeksy.runner as runner_facade
from peeksy.compare import ComparisonResult
from peeksy.config import Component, Page, Suite, Viewport
from peeksy.runner import run_generate, run_report, run_test

DESKTOP = Viewport(width=1280, height=720)
MOBILE = Viewport(width=375, height=667)
DESKTOP_LABEL = "1280x720"
MOBILE_LABEL = "375x667"


# --------------------------------------------------------------------------
# Helpers — suites, fake session, result reading
# --------------------------------------------------------------------------


def make_suite(
    tmp_path: Path,
    *,
    pages: list[Page],
    name: str = "demo-site",
    threshold: float = 0.1,
    tolerance: float = 0.5,
) -> Suite:
    """Build a `Suite` anchored at `tmp_path`."""
    return Suite(
        name=name,
        pages=pages,
        baseline_path=str(tmp_path / "baseline"),
        results_path=str(tmp_path / "results"),
        report_path=str(tmp_path / "report"),
        threshold=threshold,
        tolerance=tolerance,
    )


def make_component(name: str, **overrides: object) -> Component:
    """A component at 1280x720 by default, overridable field by field."""
    fields: dict[str, object] = {
        "name": name,
        "selector": f"#{name}",
        "viewports": [DESKTOP],
    }
    fields.update(overrides)
    return Component(**fields)  # type: ignore[arg-type]


def make_page(name: str, components: list[Component], **overrides: object) -> Page:
    """A page with a URL and the given components, overridable field by field."""
    fields: dict[str, object] = {"name": name, "url": "file:///tmp/index.html"}
    fields.update(overrides)
    return Page(components=components, **fields)  # type: ignore[arg-type]


class FakeCaptureSession:
    """Stands in for the real Playwright session.

    `capture_component` writes a small solid PNG to `out_path` (so `compare`
    has real images) and records the call. `open_page` records the viewport
    order and raises for page names listed in `fail_pages`. `open` records
    that a browser would have launched.
    """

    sessions: ClassVar[list["FakeCaptureSession"]] = []

    def __init__(
        self,
        *,
        fail_pages: set[str] | None = None,
        fail_components: set[str] | None = None,
        rgb: tuple[int, int, int] = (255, 255, 255),
    ) -> None:
        self.fail_pages = fail_pages or set()
        self.fail_components = fail_components or set()
        self.rgb = rgb
        self.opened = False
        self.closed = False
        self.open_page_calls: list[tuple[str, str]] = []
        self.captured: list[tuple[str, str]] = []

    def open(self) -> None:
        self.opened = True
        FakeCaptureSession.sessions.append(self)

    def close(self) -> None:
        self.closed = True

    def open_page(self, page: Page, viewport: Viewport) -> None:
        label = f"{viewport.width}x{viewport.height}"
        self.open_page_calls.append((page.name, label))
        if page.name in self.fail_pages:
            raise RuntimeError(f"navigation timed out for {page.name!r}")

    def capture_component(self, component: Component, out_path: str) -> str:
        self.captured.append((component.name, out_path))
        if component.name in self.fail_components:
            raise RuntimeError(f"selector {component.selector!r} not found")
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8), self.rgb).save(out_path)
        return out_path


def install_fake(monkeypatch, factory=None) -> FakeCaptureSession:
    """Patch `CaptureSession` in the runner module; return the instance it will build."""
    FakeCaptureSession.sessions = []
    instance = factory() if factory else FakeCaptureSession()
    monkeypatch.setattr("peeksy.runner.runner.CaptureSession", lambda: instance)
    return instance


def result_files(results_dir: Path) -> list[Path]:
    """Every `*-result.json` currently in the results directory."""
    return sorted(results_dir.glob("*-result.json"))


def read_result(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def find_result(results_dir: Path, page: str, name: str, viewport: str) -> dict:
    """The Allure result JSON for one (page, component, viewport) triple."""
    suffix = f" / {page} / {name} [{viewport}]"
    matches = [
        r for r in (read_result(p) for p in result_files(results_dir)) if r["name"].endswith(suffix)
    ]
    assert len(matches) == 1, f"expected exactly one result for {suffix!r}, got {len(matches)}"
    return matches[0]


def generate_baselines(monkeypatch, suite: Suite) -> None:
    """Run `run_generate` with a clean fake session (writes all baselines)."""
    install_fake(monkeypatch)
    run_generate(suite, None, None)


# --------------------------------------------------------------------------
# Contract tests — facade + signatures + package boundary
# --------------------------------------------------------------------------


def test_facade_exposes_three_routines() -> None:
    exported = set(runner_facade.__all__)
    assert exported == {"run_generate", "run_test", "run_report"}
    for routine in ("run_generate", "run_test", "run_report"):
        assert callable(getattr(runner_facade, routine))
    assert runner_facade.run_generate.__module__ == "peeksy.runner.runner"
    assert runner_facade.run_test.__module__ == "peeksy.runner.runner"
    assert runner_facade.run_report.__module__ == "peeksy.runner.runner"


def test_run_generate_signature_matches_contract() -> None:
    params = dict(inspect.signature(run_generate).parameters)
    assert list(params) == ["suite", "pages", "components"]
    assert all(p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for p in params.values())
    assert params["suite"].annotation is Suite
    assert params["pages"].annotation == (list[str] | None)
    assert params["components"].annotation == (list[str] | None)
    assert inspect.signature(run_generate).return_annotation is None


def test_run_test_signature_matches_contract() -> None:
    params = dict(inspect.signature(run_test).parameters)
    assert list(params) == ["suite", "pages", "components"]
    assert all(p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for p in params.values())
    assert params["suite"].annotation is Suite
    assert params["pages"].annotation == (list[str] | None)
    assert params["components"].annotation == (list[str] | None)
    assert inspect.signature(run_test).return_annotation is int


def test_run_report_signature_matches_contract() -> None:
    params = dict(inspect.signature(run_report).parameters)
    assert list(params) == ["suite"]
    assert params["suite"].annotation is Suite
    assert inspect.signature(run_report).return_annotation is None


def test_no_playwright_import_in_runner_cell() -> None:
    """Playwright stays inside `peeksy/capture`; the runner depends on the type only."""
    import ast

    tree = ast.parse(Path("peeksy/runner/runner.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")

    assert not any("playwright" in module for module in imported), sorted(imported)


# --------------------------------------------------------------------------
# Logic tests — filters, BROKEN policy, clearing, overrides, ordering
# --------------------------------------------------------------------------


def test_generate_and_test_honor_page_component_filters(monkeypatch, tmp_path: Path) -> None:
    suite = make_suite(
        tmp_path,
        pages=[
            make_page("home", [make_component("header"), make_component("hero")]),
            make_page("about", [make_component("sidebar")]),
        ],
    )
    session = install_fake(monkeypatch)

    run_generate(suite, pages=["home"], components=["header"])

    baseline_root = Path(suite.baseline_path)
    assert session.opened is True
    assert session.closed is True
    assert session.captured == [
        ("header", str(baseline_root / "home" / f"header_{DESKTOP_LABEL}.png"))
    ]
    assert sorted(p.name for p in baseline_root.rglob("*.png")) == [f"header_{DESKTOP_LABEL}.png"]
    assert not (baseline_root / "about").exists()
    assert not any("sidebar" in p.name for p in baseline_root.rglob("*.png"))

    exit_code = run_test(suite, pages=["home"], components=["header"])
    results_dir = Path(suite.results_path)

    assert exit_code == 0
    assert len(result_files(results_dir)) == 1
    assert (results_dir / "home" / f"header_{DESKTOP_LABEL}.current.png").exists()


def test_run_test_page_setup_failure_marks_all_components_broken(
    monkeypatch, tmp_path: Path
) -> None:
    suite = make_suite(
        tmp_path,
        pages=[
            make_page("home", [make_component("header"), make_component("hero")]),
            make_page("about", [make_component("sidebar")]),
        ],
    )
    generate_baselines(monkeypatch, suite)
    session = install_fake(monkeypatch, lambda: FakeCaptureSession(fail_pages={"home"}))

    exit_code = run_test(suite, None, None)
    results_dir = Path(suite.results_path)

    assert exit_code == 1
    assert len(result_files(results_dir)) == 3

    header = find_result(results_dir, "home", "header", DESKTOP_LABEL)
    assert header["status"] == "broken"
    assert "page setup failed" in header["statusDetails"]["message"]
    assert [a["name"] for a in header.get("attachments", [])] == []

    hero = find_result(results_dir, "home", "hero", DESKTOP_LABEL)
    assert hero["status"] == "broken"

    sidebar = find_result(results_dir, "about", "sidebar", DESKTOP_LABEL)
    assert sidebar["status"] == "passed"

    # The run continued past the failing page: about was still opened.
    assert ("about", DESKTOP_LABEL) in session.open_page_calls


def test_run_test_missing_baseline_is_broken(monkeypatch, tmp_path: Path) -> None:
    suite = make_suite(tmp_path, pages=[make_page("home", [make_component("header")])])
    install_fake(monkeypatch)  # no generate step — baseline absent

    exit_code = run_test(suite, None, None)

    assert exit_code == 1
    (result,) = (read_result(p) for p in result_files(Path(suite.results_path)))
    assert result["status"] == "broken"
    assert "baseline not found" in result["statusDetails"]["message"]
    assert "peeksy generate" in result["statusDetails"]["message"]
    # No comparison happened, so there is no mismatch % and no images at all.
    assert [a["name"] for a in result.get("attachments", [])] == []


def test_run_test_empty_selection_is_noop_preserving_results(monkeypatch, tmp_path: Path) -> None:
    suite = make_suite(tmp_path, pages=[make_page("home", [make_component("header")])])
    generate_baselines(monkeypatch, suite)
    run_test(suite, None, None)
    results_dir = Path(suite.results_path)
    before = len(result_files(results_dir))

    session = install_fake(monkeypatch)

    def explode() -> None:
        raise AssertionError("CaptureSession.open() must not be called for an empty selection")

    session.open = explode  # type: ignore[method-assign]

    assert run_test(suite, pages=["nonexistent"]) == 0
    assert session.opened is False
    assert len(result_files(results_dir)) == before


def test_results_dir_cleared_between_test_runs(monkeypatch, tmp_path: Path) -> None:
    suite = make_suite(tmp_path, pages=[make_page("home", [make_component("header")])])
    generate_baselines(monkeypatch, suite)

    assert run_test(suite, None, None) == 0
    results_dir = Path(suite.results_path)
    assert len(result_files(results_dir)) == 1

    # A leftover from a run whose component no longer exists.
    stale_json = results_dir / "00000000-dead-beef-0000-000000000000-result.json"
    stale_json.write_text("{}", encoding="utf-8")
    stale_attachment = results_dir / "00000000-dead-beef-0000-000000000001-attachment"
    stale_attachment.write_bytes(b"png")

    assert run_test(suite, None, None) == 0

    assert len(result_files(results_dir)) == 1
    assert not stale_json.exists()
    assert not stale_attachment.exists()
    # The current-run captures survive the clear.
    current = results_dir / "home" / f"header_{DESKTOP_LABEL}.current.png"
    assert current.exists()


def test_run_test_wipes_stale_page_subdir_of_removed_component(monkeypatch, tmp_path: Path) -> None:
    suite = make_suite(
        tmp_path,
        pages=[make_page("home", [make_component("header"), make_component("removed")])],
    )
    generate_baselines(monkeypatch, suite)
    run_test(suite, None, None)
    results_dir = Path(suite.results_path)
    stale = results_dir / "home" / f"removed_{DESKTOP_LABEL}.current.png"
    assert stale.exists()

    # The component disappears from the suite before the next run.
    suite = make_suite(tmp_path, pages=[make_page("home", [make_component("header")])])
    install_fake(monkeypatch)
    assert run_test(suite, None, None) == 0

    assert not stale.exists()
    assert not (results_dir / "home" / f"removed_{DESKTOP_LABEL}.diff.png").exists()


def test_component_threshold_override_wins_over_suite_default(monkeypatch, tmp_path: Path) -> None:
    forwarded: list[dict] = []

    def fake_compare(
        baseline: str, current: str, diff_dir: str, threshold: float, tolerance: float
    ):
        forwarded.append({"current": current, "threshold": threshold, "tolerance": tolerance})
        return ComparisonResult(passed=True, mismatch_percent=0.0, diff_path=None)

    monkeypatch.setattr("peeksy.runner.runner.compare", fake_compare)
    suite = make_suite(
        tmp_path,
        threshold=0.1,
        tolerance=0.5,
        pages=[
            make_page(
                "home",
                [
                    make_component("default"),
                    make_component("overridden", threshold=0.3, tolerance=4.0),
                ],
            )
        ],
    )
    generate_baselines(monkeypatch, suite)

    assert run_test(suite, None, None) == 0
    by_name = {Path(f["current"]).name: f for f in forwarded}
    assert by_name[f"default_{DESKTOP_LABEL}.current.png"]["threshold"] == 0.1
    assert by_name[f"default_{DESKTOP_LABEL}.current.png"]["tolerance"] == 0.5
    assert by_name[f"overridden_{DESKTOP_LABEL}.current.png"]["threshold"] == 0.3
    assert by_name[f"overridden_{DESKTOP_LABEL}.current.png"]["tolerance"] == 4.0


def test_component_tolerance_override_decides_failure(monkeypatch, tmp_path: Path) -> None:
    """Same 6.25% mismatch: fails at the suite default, passes at the override."""
    suite = make_suite(
        tmp_path,
        tolerance=1.0,
        pages=[
            make_page(
                "home",
                [
                    make_component("loose", tolerance=50.0),
                    make_component("strict", tolerance=1.0),
                ],
            )
        ],
    )
    generate_baselines(monkeypatch, suite)

    # Same 8x8 canvas as the baseline (a size change would be an instant 100%),
    # with 4 of the 64 pixels blackened -> 6.25% mismatch.
    def slightly_changed(self, component, out_path):
        from PIL import Image as PILImage

        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        image = PILImage.new("RGB", (8, 8), (255, 255, 255))
        for x in range(4):
            image.putpixel((x, 0), (0, 0, 0))
        image.save(out_path)
        return out_path

    monkeypatch.setattr(FakeCaptureSession, "capture_component", slightly_changed)
    exit_code = run_test(suite, None, None)
    results_dir = Path(suite.results_path)

    assert exit_code == 1
    assert find_result(results_dir, "home", "strict", DESKTOP_LABEL)["status"] == "failed"
    assert find_result(results_dir, "home", "loose", DESKTOP_LABEL)["status"] == "passed"
    assert (results_dir / "home" / f"strict_{DESKTOP_LABEL}.diff.png").exists()
    assert not (results_dir / "home" / f"loose_{DESKTOP_LABEL}.diff.png").exists()


def test_viewport_dedupe_preserves_first_seen_order(monkeypatch, tmp_path: Path) -> None:
    # The config layer sorts components by name: `wide` precedes `zoom`, so the
    # first-seen viewport order is DESKTOP (wide's only viewport) then MOBILE.
    suite = make_suite(
        tmp_path,
        pages=[
            make_page(
                "home",
                [
                    make_component("wide", viewports=[DESKTOP]),
                    make_component("zoom", viewports=[MOBILE, DESKTOP]),
                ],
            )
        ],
    )
    session = install_fake(monkeypatch)

    run_generate(suite, None, None)

    # open_page once per (page, viewport) — never per component.
    assert session.open_page_calls == [
        ("home", DESKTOP_LABEL),
        ("home", MOBILE_LABEL),
    ]
    # At DESKTOP both components shoot (name-sorted); at MOBILE only `zoom`.
    assert [(name, Path(p).name) for name, p in session.captured] == [
        ("wide", f"wide_{DESKTOP_LABEL}.png"),
        ("zoom", f"zoom_{DESKTOP_LABEL}.png"),
        ("zoom", f"zoom_{MOBILE_LABEL}.png"),
    ]


def test_exit_code_zero_when_all_passed_and_one_json_per_outcome(
    monkeypatch, tmp_path: Path
) -> None:
    suite = make_suite(
        tmp_path,
        pages=[
            make_page("home", [make_component("header", viewports=[DESKTOP, MOBILE])]),
        ],
    )
    generate_baselines(monkeypatch, suite)

    assert run_test(suite, None, None) == 0

    results_dir = Path(suite.results_path)
    assert len(result_files(results_dir)) == 2
    assert find_result(results_dir, "home", "header", DESKTOP_LABEL)["status"] == "passed"
    assert find_result(results_dir, "home", "header", MOBILE_LABEL)["status"] == "passed"


def test_run_report_delegates_to_build_report(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def fake_build_report(results_dir: str, report_dir: str) -> None:
        calls.append((results_dir, report_dir))

    monkeypatch.setattr("peeksy.runner.runner.build_report", fake_build_report)
    suite = make_suite(tmp_path, pages=[])

    assert run_report(suite) is None

    assert calls == [(suite.results_path, suite.report_path)]


def test_generate_is_fail_fast_and_closes_session(monkeypatch, tmp_path: Path) -> None:
    suite = make_suite(
        tmp_path,
        pages=[
            make_page("home", [make_component("header"), make_component("hero")]),
            make_page("about", [make_component("sidebar")]),
        ],
    )
    session = install_fake(monkeypatch, lambda: FakeCaptureSession(fail_components={"header"}))

    try:
        run_generate(suite, None, None)
        raised = False
    except RuntimeError:
        raised = True

    assert raised is True
    assert session.closed is True
    # The first error aborted the run: nothing after `header` was captured.
    assert [name for name, _ in session.captured] == ["header"]
    assert not (Path(suite.baseline_path) / "about").exists()


def test_run_test_capture_error_is_broken_not_fatal(monkeypatch, tmp_path: Path) -> None:
    suite = make_suite(
        tmp_path,
        pages=[make_page("home", [make_component("header"), make_component("missing")])],
    )
    generate_baselines(monkeypatch, suite)
    session = install_fake(monkeypatch, lambda: FakeCaptureSession(fail_components={"missing"}))

    exit_code = run_test(suite, None, None)
    results_dir = Path(suite.results_path)

    assert exit_code == 1
    assert session.closed is True
    header = find_result(results_dir, "home", "header", DESKTOP_LABEL)
    assert header["status"] == "passed"
    broken = find_result(results_dir, "home", "missing", DESKTOP_LABEL)
    assert broken["status"] == "broken"
    assert "selector" in broken["statusDetails"]["message"]
