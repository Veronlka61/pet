# reporting — Allure Results and HTML Report

## Domain

How to turn component outcomes into Allure result data and build the browsable HTML
report. Target audience: the `runner` cell.

## Stage 1 — write results

```python
from peeksy.reporting import write_results, Outcome

outcomes = [
    Outcome(
        suite="example.com",
        page="home",
        name="header",
        viewport="1280x720",
        status="FAILED",
        mismatch_percent=2.34,
        baseline_path="baselines/home/header_1280x720.png",
        current_path="results/home/header_1280x720.current.png",
        diff_path="results/home/header_1280x720.diff.png",
        error=None,
    ),
    # BROKEN: capture failed — no current PNG, no comparison, mismatch_percent is None
    Outcome(
        suite="example.com",
        page="home",
        name="sidebar",
        viewport="1280x720",
        status="BROKEN",
        mismatch_percent=None,
        baseline_path="baselines/home/sidebar_1280x720.png",
        current_path=None,
        diff_path=None,
        error="selector '.sidebar' not found within timeout",
    ),
]
write_results(outcomes, results_dir="results")
```

- One result JSON is written per `Outcome`; the display name is `{suite} / {page} / {name} [{viewport}]`.
- `testCaseId`/`historyId` are `peeksy::{suite}::{page}::{name}[{viewport}]` (suite+page-namespaced,
  viewport-suffixed — the same component name on different pages, different sites, or at different
  viewports never collapses in history/trends).
- The Allure suite label carries the real site name from `suite`.
- `status` PASSED/FAILED is the visual verdict; BROKEN is an infrastructure failure, shown with its `error` message.
- Attachments are written only for non-None paths — a BROKEN outcome with `current_path=None` simply omits the current image.
- `statusDetails` carries the mismatch percent when FAILED, or the `error` reason when BROKEN
  (`mismatch_percent` is `None` for BROKEN — never a fake `0.0` in numeric filtering).

## Stage 2 — build the HTML report

```python
from peeksy.reporting import build_report

build_report(results_dir="results", report_dir="report")
```

Requires the external `allure` CLI (Java/JDK) on PATH.