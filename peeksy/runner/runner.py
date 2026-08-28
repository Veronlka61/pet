"""Orchestration of a peeksy run: `generate`, `test`, and `report` over a `Suite`.

Contract source: `peeksy/runner/CODEMANIFEST` (read-only); policies per the
inline `run_policy` usage. This cell owns no Playwright knowledge — it drives
`CaptureSession` from the capture cell and the compare/reporting cells' types.

The two runs differ in failure policy:

- `generate` is fail-fast: the first capture error closes the session and
  propagates (re-run with `--page`/`--component` to resume).
- `test` never aborts on capture errors — they become BROKEN outcomes. Only a
  fully PASSED run returns 0.

Capture is grouped by (page, viewport): `open_page` runs once per viewport,
then each component at that viewport is captured in name-sorted order. Viewport
dedupe is an ordered first-seen scan (`Viewport` is a Pydantic model, hence
unhashable — no `set` iteration anywhere).
"""

import shutil
from pathlib import Path

from peeksy.capture import CaptureSession
from peeksy.compare import ComparisonResult, compare
from peeksy.config import Component, Page, Suite, Viewport
from peeksy.reporting import Outcome, build_report, write_results

_BASELINE_MISSING = "baseline not found; run `peeksy generate`"


def run_generate(
    suite: Suite, pages: list[str] | None = None, components: list[str] | None = None
) -> None:
    """Capture and store baselines for the selected pages/components."""
    selected = _filter_pages(suite.pages, pages, components)
    if not selected:
        return  # a no-op run must not launch a browser

    session = CaptureSession()
    try:
        session.open()
        for page, page_components in selected:
            for viewport, at_viewport in _group_by_viewport(page_components):
                session.open_page(page, viewport)
                for component in at_viewport:
                    session.capture_component(
                        component, _baseline_png(suite, page, component, viewport)
                    )
    finally:
        session.close()


def run_test(
    suite: Suite, pages: list[str] | None = None, components: list[str] | None = None
) -> int:
    """Capture, compare against baselines, and write Allure outcomes."""
    selected = _filter_pages(suite.pages, pages, components)
    if not selected:
        return 0  # nothing selected: no browser, and prior results stay untouched

    outcomes: list[Outcome] = []
    session = CaptureSession()
    try:
        session.open()
        # Stale `.current.png`/`.diff.png` of renamed/removed components would
        # accumulate forever — the exact-pattern clear below never matches them.
        # Only after a successful launch: wiping the previous run's images while
        # its `*-result.json` files still reference them would leave the report
        # pointing at deleted attachments.
        for page, _ in selected:
            _reset_page_results(suite, page)
        for page, page_components in selected:
            for viewport, at_viewport in _group_by_viewport(page_components):
                outcomes.extend(_run_viewport(suite, session, page, viewport, at_viewport))
    finally:
        session.close()

    _clear_prior_results(suite.results_path)
    write_results(outcomes, suite.results_path)
    return 0 if outcomes and all(outcome.status == "PASSED" for outcome in outcomes) else 1


def run_report(suite: Suite) -> None:
    """Build the Allure HTML report from the results directory."""
    build_report(suite.results_path, suite.report_path)


# --------------------------------------------------------------------------
# Private helpers — one viewport's outcomes, grouping, paths, clearing
# --------------------------------------------------------------------------


def _run_viewport(
    suite: Suite,
    session: CaptureSession,
    page: Page,
    viewport: Viewport,
    at_viewport: list[Component],
) -> list[Outcome]:
    """Open the page at `viewport` and judge every component on it."""
    label = _viewport_label(viewport)
    try:
        session.open_page(page, viewport)
    except Exception as error:  # noqa: BLE001 — infrastructure, not a regression
        return [
            _broken(
                suite,
                page.name,
                component.name,
                label,
                error=f"page setup failed: {error}",
                # An existing baseline stays attached — run_policy: the path is
                # None only when the image does not exist.
                baseline_path=_existing_baseline(suite, page, component, viewport),
            )
            for component in at_viewport
        ]

    outcomes: list[Outcome] = []
    for component in at_viewport:
        current = _current_png(suite, page, component, viewport)
        baseline = _baseline_png(suite, page, component, viewport)
        baseline_path = _existing_baseline(suite, page, component, viewport)
        try:
            session.capture_component(component, current)
        except Exception as error:  # noqa: BLE001
            outcomes.append(
                _broken(
                    suite,
                    page.name,
                    component.name,
                    label,
                    error=str(error),
                    baseline_path=baseline_path,
                )
            )
            continue

        if baseline_path is None:
            outcomes.append(
                _broken(
                    suite,
                    page.name,
                    component.name,
                    label,
                    error=_BASELINE_MISSING,
                    baseline_path=None,
                )
            )
            continue

        try:
            result = _compare_component(suite, component, baseline, current)
        except Exception as error:  # noqa: BLE001 — e.g. an unreadable baseline PNG
            # An unreadable/corrupt baseline is infrastructure damage, not a
            # visual regression — and it must never abort the run: `test`
            # records it BROKEN like any capture error and keeps reporting the
            # remaining components.
            outcomes.append(
                _broken(
                    suite,
                    page.name,
                    component.name,
                    label,
                    error=f"comparison failed: {error}",
                    baseline_path=baseline_path,
                )
            )
            continue
        outcomes.append(
            Outcome(
                suite=suite.name,
                page=page.name,
                name=component.name,
                viewport=label,
                status="PASSED" if result.passed else "FAILED",
                mismatch_percent=result.mismatch_percent,
                baseline_path=baseline,
                current_path=current,
                diff_path=result.diff_path,
                error=None,
            )
        )
    return outcomes


def _compare_component(
    suite: Suite, component: Component, baseline: str, current: str
) -> ComparisonResult:
    """Compare with the effective thresholds: component override ?? suite default."""
    threshold = component.threshold if component.threshold is not None else suite.threshold
    tolerance = component.tolerance if component.tolerance is not None else suite.tolerance
    return compare(baseline, current, str(Path(current).parent), threshold, tolerance)


def _filter_pages(
    all_pages: list[Page], pages: list[str] | None, components: list[str] | None
) -> list[tuple[Page, list[Component]]]:
    """Apply the page/component name filters (None => all); drop empty pages.

    A filter that matches nothing is a config mistake (a renamed page turning
    the CI gate into a no-op that can never fail), so it raises rather than
    returning an empty selection — which the callers treat as "suite is empty".
    """
    wanted_pages = None if pages is None else set(pages)
    wanted_components = None if components is None else set(components)
    selected: list[tuple[Page, list[Component]]] = []

    for page in all_pages:
        if wanted_pages is not None and page.name not in wanted_pages:
            continue
        kept = [
            component
            for component in page.components  # already name-sorted by the config layer
            if wanted_components is None or component.name in wanted_components
        ]
        if kept:
            selected.append((page, kept))

    if not selected:
        _reject_unknown_filters(all_pages, pages, components, wanted_pages, wanted_components)
    return selected


def _reject_unknown_filters(
    all_pages: list[Page],
    pages: list[str] | None,
    components: list[str] | None,
    wanted_pages: set[str] | None,
    wanted_components: set[str] | None,
) -> None:
    """Raise naming every filter value no page/component answers to.

    Reached only when the selection is empty: an empty `suite.pages` (a genuine
    no-op run) passes through untouched, and the filters are checked only
    against pages/components that would otherwise have been selected.
    """
    if not all_pages:
        return
    known_pages = {page.name for page in all_pages}
    problems: list[str] = []
    if wanted_pages is not None:
        problems.extend(f"unknown page {name!r}" for name in pages or [] if name not in known_pages)
    if wanted_components is not None:
        known_on_kept_pages = {
            c.name
            for page in all_pages
            if wanted_pages is None or page.name in wanted_pages
            for c in page.components
        }
        problems.extend(
            f"unknown component {name!r}"
            for name in components or []
            if name not in known_on_kept_pages
        )
    if problems:
        raise ValueError(
            f"filter matched nothing: {'; '.join(sorted(problems))} "
            f"(known pages: {sorted(known_pages)})"
        )


def _group_by_viewport(components: list[Component]) -> list[tuple[Viewport, list[Component]]]:
    """Group components by viewport, preserving first-seen viewport order."""
    ordered: list[Viewport] = []
    for component in components:  # name-sorted -> deterministic first-seen order
        for viewport in component.viewports:
            if viewport not in ordered:  # list scan: Viewport is unhashable
                ordered.append(viewport)

    return [(viewport, [c for c in components if viewport in c.viewports]) for viewport in ordered]


def _viewport_label(viewport: Viewport) -> str:
    """`1280x720` — used in paths, `Outcome.viewport`, and the testCaseId."""
    return f"{viewport.width}x{viewport.height}"


def _baseline_png(suite: Suite, page: Page, component: Component, viewport: Viewport) -> str:
    """`{baseline_path}/{page}/{name}_{WxH}.png` per `run_policy`."""
    return str(
        Path(suite.baseline_path) / page.name / f"{component.name}_{_viewport_label(viewport)}.png"
    )


def _existing_baseline(
    suite: Suite, page: Page, component: Component, viewport: Viewport
) -> str | None:
    """The baseline path when the PNG exists, else None (per `run_policy`)."""
    baseline = _baseline_png(suite, page, component, viewport)
    return baseline if Path(baseline).exists() else None


def _current_png(suite: Suite, page: Page, component: Component, viewport: Viewport) -> str:
    """`{results_path}/{page}/{name}_{WxH}.current.png` per `run_policy`."""
    return str(
        Path(suite.results_path)
        / page.name
        / f"{component.name}_{_viewport_label(viewport)}.current.png"
    )


def _reset_page_results(suite: Suite, page: Page) -> None:
    """Drop the page's results subdirectory so removed components leave no PNGs."""
    shutil.rmtree(Path(suite.results_path) / page.name, ignore_errors=True)


def _clear_prior_results(results_path: str) -> None:
    """Remove prior `*-result.json` / `*-attachment` files — exact patterns only.

    Current-run `.current.png`/`.diff.png` files live in per-page subdirectories
    and never match these patterns, so they survive.
    """
    results = Path(results_path)
    if not results.is_dir():
        return
    for pattern in ("*-result.json", "*-attachment"):
        for stale in results.glob(pattern):
            stale.unlink()


def _broken(
    suite: Suite,
    page: str,
    name: str,
    viewport: str,
    *,
    error: str,
    baseline_path: str | None = None,
) -> Outcome:
    """A BROKEN outcome — an infrastructure failure, never a visual regression."""
    return Outcome(
        suite=suite.name,
        page=page,
        name=name,
        viewport=viewport,
        status="BROKEN",
        mismatch_percent=None,  # no comparison happened — never a fake 0.0
        baseline_path=baseline_path,
        current_path=None,
        diff_path=None,
        error=error,
    )
