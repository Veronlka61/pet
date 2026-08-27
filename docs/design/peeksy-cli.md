# Design Document: `peeksy-cli`

A complete architectural specification for implementing the peeksy visual-regression CLI from
scratch (greenfield). Every cell, entity, and entry point is elaborated: interaction flows,
code-stack traces, algorithms, cross-cutting concerns, usages, and test scenarios.

- **Topic**: `peeksy-cli`
- **Source architecture**: `docs/arch/peeksy-cli.md`
- **Source task**: `docs/tasks/peeksy-cli.md`
- **Language**: Python (cell = package with `CODEMANIFEST` + `__init__.py`)
- **Base usages/annotations**: none (`.goga/config.yml` absent)

---

## Contract Changes

This is a greenfield implementation. Every cell is **new**; the "change" is the full contract.

### Changed CODEMANIFEST Files
All six are new (created by `goga-apply`):

- `peeksy/config/CODEMANIFEST` — config data model + site-folder loader
- `peeksy/compare/CODEMANIFEST` — pixelmatch comparison
- `peeksy/reporting/CODEMANIFEST` — Allure results writer + HTML report builder
- `peeksy/capture/CODEMANIFEST` — Playwright capture session (two-level setup)
- `peeksy/runner/CODEMANIFEST` — generate/test/report orchestration
- `peeksy/cli/CODEMANIFEST` — Typer facade + console entry point

### New Entities
- `Viewport` (config, `models.py`) — CSS pixel dimensions.
- `Action` (config, `models.py`) — one setup action; kinds: click, hover, scroll_to, scroll_by, fill, press, select, wait, open, reload.
- `Component` (config, `models.py`) — one UI component spec on a page.
- `Page` (config, `models.py`) — one page (url + page-level setup + components).
- `Suite` (config, `models.py`) — whole site configuration.
- `ComparisonResult` (compare, `result.py`) — image-comparison verdict.
- `Outcome` (reporting, `outcome.py`) — one reportable (page, component, viewport) result.
- `CaptureSession` (capture, `session.py`) — Playwright lifecycle + two-level capture.

### New Routines
- `load_config` (config, `loader.py`)
- `compare` (compare, `compare.py`)
- `write_results`, `build_report` (reporting, `writer.py`, `report.py`)
- `run_generate`, `run_test`, `run_report` (runner, `runner.py`)
- `generate`, `test`, `report`, `main` (cli, `app.py`)

### Usages and Annotations Changes
- Project-level practices (`.goga/usages/cooks/`): `playwright.md`, `image-diff.md`, `allure.md` (already authored, extended with the `open` action row and `run_actions` example).
- Inline practices: `pydantic_config` (config), `run_policy` (runner), `typer` (cli).
- Cell-level `.usages/`: one consumer doc per cell (`config.md`, `compare.md`, `reporting.md`, `capture.md`, `runner.md`, `cli.md`).

---

## Applied Fixes

### Fixed CODEMANIFEST Defects
The contract was validated by `goga-review-arch` and `goga lint` (cells: 6, errors: 0). No
outstanding contract defects. Earlier defects that were fixed before this design:

- `capture`: added the missing `|` block-scalar markers on `open_page`/`capture_component` method values (YAML parser failed on `` `page`: ``).
- All cells: 146 invalid backtick references resolved (`annotation_links_exists`) — kept backticks only for valid type/practice/own-signature-param targets.
- `kind=open` rippled consistently across `config`, `capture`, `playwright.md`, `.usages/config.md`.

No CODEMANIFEST edits are required to proceed to implementation.

---

## Entity Interaction and Data Flow

### Interaction Diagram

```
                         ┌─────────── peeksy/cli (app.py) ───────────┐
                         │  generate / test / report / main           │
                         └───────┬───────────────────┬────────────────┘
                                 │ load_config        │ run_*
                                 ▼                    ▼
   ┌──── peeksy/config ────┐            ┌──────────── peeksy/runner ────────────┐
   │ Suite/Page/Component/ │  Suite     │ run_generate / run_test / run_report   │
   │ Viewport/Action       │◄───────────┤                                        │
   │ load_config           │            │  CaptureSession   compare   Outcome    │
   └────────▲──────────────┘            └───┬──────────────┬─────────────┬───────┘
            │                               │              │             │
   ┌────────┴─────── peeksy/capture ────────┘    ┌─────────┴───┐  ┌──────┴─────────┐
   │ CaptureSession: open / open_page /          │ peeksy/      │  │ peeksy/        │
   │ capture_component / close  (Playwright)      │ compare      │  │ reporting      │
   └─────────────────────────────────────────────└──────────────┘  │ write_results  │
                                                                   │ build_report   │
                                                                   └────────────────┘
```

### Data Flows

1. **generate**: `cli.generate → load_config(path) → Suite → run_generate(suite, pages, components) → CaptureSession.open → (per page,viewport: open_page → capture_component → baseline PNG) → CaptureSession.close`.
2. **test**: `cli.test → load_config → Suite → run_test → CaptureSession.open → (per page,viewport: open_page → capture_component → compare → Outcome) → clear results → write_results → exit_code → cli prints summary → typer.Exit(code)`.
3. **report**: `cli.report → load_config → Suite → run_report → build_report(results_path, report_path) → allure CLI`.

### Entity Dependencies (initialization order)

Leaves first: `config` → (`compare`, `reporting`) → `capture` → `runner` → `cli`. `CaptureSession`
is constructed by the runner and lives for one run; it owns one Playwright browser + context
(DPR=1) and one reusable page. `Suite` is constructed once by `load_config`.

---

## Code Stack Trace

### Trace: `load_config(path: str) -> Suite`

1. **Input**: `path` — a suite file path (any explicitly passed `*.yml` — `peeksy.yml` in the project root by convention, default of `--config`), or a site folder. → checkpoint: path exists (IO error otherwise).
2. Resolve site dir: an explicitly passed `*.yml` file IS the suite file → use its parent as the site dir; a folder → look up `suite.yml` inside it. → checkpoint: the suite file exists under the resolved dir.
3. Read + validate the resolved suite file into suite meta (`name`, `baseline_path`, `results_path`, `report_path`, `threshold`, `tolerance`) via Pydantic; normalize relative paths to absolute **against the site folder** (CWD-independence). → checkpoint: `ValidationError` on bad YAML/types/out-of-range threshold/tolerance, surfaced human-readable.
4. Enumerate `pages/*/` subfolders. For each: read `page.yml` (`url`, `setup`); discover components as the other `*.yml` files in that folder. → checkpoint: `page.yml` required; non-`*.yml` files ignored.
5. Parse each component file: short-form `setup` actions → `Action(kind, target, value)` per per-kind rules; derive `Component.name` from filename, `Page.name` from folder name. → checkpoint: `ValueError` on malformed action (e.g. `fill` without list); `ValidationError` on out-of-range overrides, non-positive viewport dimensions, or empty `viewports`.
6. Per-page uniqueness: `model_validator` rejects duplicate `Component.name` within a page. → checkpoint: dup → `ValidationError`.
7. **Output**: `Suite` with `pages`. Consumer: `runner` / `cli`.

**Checkpoint Summary**: all passed; the only failure modes are IO (`FileNotFoundError`) and validation (`pydantic.ValidationError`), both surfaced as human-readable messages.

### Trace: `compare(baseline, current, diff_dir, threshold, tolerance) -> ComparisonResult`

1. **Input**: two PNG paths, `diff_dir`, `threshold` (0..1), `tolerance` (%). → checkpoint: both files exist (caller — runner — guarantees baseline existence; current captured just before).
2. `Image.open(...).convert("RGBA")` for both. → checkpoint: identical sizes required by pixelmatch.
3. If sizes differ → return `ComparisonResult(passed=False, mismatch_percent=100.0, diff_path=None)`. → checkpoint: size change is a definite regression.
4. `pixelmatch(baseline, current, diff, threshold=threshold, includeAA=True)` → mismatched count.
5. `mismatch_percent = mismatched / (w*h) * 100`. `passed = mismatch_percent <= tolerance`.
6. If not passed → save diff to `diff_dir`, set `diff_path`; else `diff_path=None`.
7. **Output**: `ComparisonResult`. Consumer: `runner`.

### Trace: `write_results(outcomes, results_dir)`

1. **Input**: `list[Outcome]`, `results_dir`.
2. Create `results_dir` (mkdir, parents) if absent. → checkpoint: writing succeeds on a fresh site checkout.
3. For each `Outcome`: compute `testCaseId`/`historyId` = `peeksy::{suite}::{page}::{name}[{viewport}]`; display name `{suite} / {page} / {name} [{viewport}]`; Allure suite label = `suite`. → checkpoint: stable across runs; never collapses across sites, pages, or viewports (one history row per (component, viewport)).
4. For non-None among `baseline_path`/`current_path`/`diff_path`: copy PNG into `results_dir` as `<uuid>-attachment`; skip None. → checkpoint: BROKEN outcomes omit the missing image cleanly.
5. Build `TestResult` (allure-commons): status mapped PASSED→`Status.PASSED`, FAILED→`Status.FAILED`, BROKEN→`Status.BROKEN`; attach copied PNGs.
6. `statusDetails`: mismatch `%` when FAILED; `error` message when BROKEN.
7. Write `<uuid>-result.json`. → checkpoint: one JSON per Outcome.
8. **Output**: populated `results_dir`. No return value. Clearing prior runs is the runner's responsibility.

### Trace: `build_report(results_dir, report_dir)`

1. **Input**: results dir, report dir.
2. `shutil.which("allure")` → if None: raise a human-readable error with install instructions. → checkpoint: never let `subprocess` fail with `FileNotFoundError`.
3. `subprocess.run(["allure","generate",results_dir,"--clean","-o",report_dir], check=True, capture_output=True)`. → checkpoint: non-zero exit raises `CalledProcessError` (with captured stderr surfaced); positional results dir first — canonical `allure generate` argument order.
4. **Output**: HTML report in `report_dir`.

### Trace: `CaptureSession.open()`

1. **Input**: none (constructor stored nothing yet).
2. `sync_playwright().start()`; `p.chromium.launch(headless=True)`; `browser.new_context(device_scale_factor=1)`; `context.new_page()`. Store on self.
3. **Output**: session ready for `open_page`.

### Trace: `CaptureSession.open_page(page, viewport)`

1. **Input**: `Page`, `Viewport`.
2. `page.set_viewport_size({"width":vp.width,"height":vp.height})`.
3. If `page.url` is not None: `page.goto(page.url, wait_until=page.wait_until)` — strategy from the config (`networkidle` by default; `domcontentloaded`/`load` for live pages). When `url` is None (deep-link flow — validated to start with an `open` action), navigation is performed by that first setup action.
4. Inject CSS disabling animations/transitions + `caret-color: transparent`; `page.evaluate("document.fonts.ready")`.
5. For each `Action` in `page.setup`: execute via Playwright per `kind` (see `run_actions`).
6. **Output**: page settled; ready for `capture_component` at this viewport.

### Trace: `CaptureSession.capture_component(component, out_path) -> str`

1. **Input**: `Component`, `out_path`.
2. For each `Action` in `component.setup`: execute per `kind`.
2.5 Re-apply the determinism CSS (animation-disable + `caret-color`) and `document.fonts.ready` — an `open`/`reload` inside the setup navigates away and drops the `<style>` injected by `open_page` (and the deep-link flow injects it on a blank page). → checkpoint: determinism holds even for `- reload: {}` components and deep-link pages.
3. Locate `component.selector` — plain CSS, piercing (`a >> b`), or iframe (`frame_locator(...).locator(...)`) — `.first`; `wait_for(state="visible")`. → checkpoint: page settled before masking — masked zones exist in the DOM.
4. For each `mask_selectors`: lay an opaque gray `::after` overlay over `locate(page, sel)` — the SAME helper as for the component selector — by injecting a `.peeksy-mask` class (`add_style_tag` + `evaluate`). → checkpoint: pixel-identical masks regardless of underlying content; never `display:none` (preserve layout box); masks symmetric with the component selector.
5. `screenshot(type="png", path=out_path)`.
6. Remove the `peeksy-mask` class from every masked element (same locate helper). → checkpoint: the next capture on this page starts unmasked — no mask leakage across components.
7. **Output**: `out_path` (== written PNG path).

### Trace: `CaptureSession.close()`

1. `context.close()`; `browser.close()`; stop playwright. → checkpoint: idempotent teardown.

### Trace: `run_generate(suite, pages, components)`

1. **Input**: `Suite`, optional name filters.
2. Filter `suite.pages` by `pages`; within each page filter `components` by name (None ⇒ all). If the filtered result is empty, return immediately WITHOUT opening the CaptureSession (no browser launch for a no-op run).
3. `CaptureSession.open()`; capture loop in try/finally (fail-fast: the first capture error closes the session and propagates; re-run with `--page`/`--component` to resume).
4. For each page: ordered dedupe of viewports across its filtered components (first-seen order over the name-sorted components — deterministic, no set iteration since `Viewport` is unhashable); for each viewport: `open_page(page, viewport)`; for each component at that viewport (name-sorted order — deterministic regardless of filesystem ordering): `capture_component` into `{baseline_path}/{page}/{name}_{WxH}.png`.
5. `CaptureSession.close()` in the finally block.
6. **Output**: baseline PNGs written. No return.

### Trace: `run_test(suite, pages, components) -> int`

1. **Input**: `Suite`, filters.
2. Filter pages/components. If the filtered result is empty (or `suite.pages` is empty), return `0` immediately WITHOUT opening the CaptureSession and WITHOUT clearing/writing results.
2.5 BEFORE the capture loop: remove the nested `{results_path}/{page}/` subdirectories — stale `.current.png`/`.diff.png` of renamed/removed components would otherwise accumulate forever (the exact-pattern clear below never matches them). The current run re-creates these subdirectories as it captures. → checkpoint: no stale per-page PNGs survive a rename/removal.
3. `CaptureSession.open()`; `outcomes = []`; capture loop in try/finally.
4. For each page: ordered dedupe of viewports (first-seen over name-sorted components); for each viewport:
   - try `open_page(page, viewport)`; except → append BROKEN `Outcome` (error "page setup failed: …", `current_path=None`) for every component at that viewport; continue.
   - for each component at this viewport (name-sorted order):
     - try `capture_component` → current `{results_path}/{page}/{name}_{WxH}.current.png`; except → BROKEN (error, `current_path=None`); continue.
     - if baseline `{baseline_path}/{page}/{name}_{WxH}.png` missing → BROKEN (error "baseline not found; run `peeksy generate`"); continue.
     - resolve effective `threshold`/`tolerance` = component override ?? suite default.
     - `compare(...)` → `ComparisonResult`; status PASSED/FAILED.
     - append PASSED/FAILED `Outcome` (paths, mismatch %, error None).
5. `CaptureSession.close()` in the finally block — the browser is torn down even on an unexpected error.
6. Clear `results_path` of prior-run artifacts ONLY by exact patterns: `*-result.json` and `*-attachment` files (previous runs' copies). Current-run PNGs live as `{page}/{name}_{WxH}.current.png` / `.diff.png` and are NOT matched by the patterns — never clear the whole directory (the per-page subdirectories were already reset in step 2.5). → checkpoint: runs never silently mix; current captures survive the clear.
7. `write_results(outcomes, results_path)`.
8. **Output**: `0` if all PASSED else `1`.

### Trace: `run_report(suite)`

1. `build_report(suite.results_path, suite.report_path)`. Propagates the missing-allure error to `cli`.

### Trace: `cli.generate / test / report`

1. `load_config(config_path)` → `Suite`. Configuration errors are caught by a single app-level Typer exception handler: `pydantic.ValidationError` (bad types/duplicates/ranges), `yaml.YAMLError` (syntactically broken YAML never reaches Pydantic), `FileNotFoundError`/`NotADirectoryError` (missing `--config` path) — printed as a human-readable message (no Python traceback), then `typer.Exit(code=1)` — applies to all three commands.
2. Delegate to runner (`run_generate`/`run_test`/`run_report`) with `page`/`component` filters.
3. `test`: print one-line summary from exit code; `raise typer.Exit(code=exit_code)`.
4. `report`: catch missing-allure error → print install message + `typer.Exit(code=1)`.
5. `main`: run the Typer app.

**Checkpoint Summary**: all entry points passed; the contract cleanly separates infrastructure failure (`BROKEN`), visual regression (`FAILED`), and success (`PASSED`); exit codes are CI-friendly and pytest-interceptable via `typer.Exit`.

---

## Algorithm Design

### `Viewport` / `Action` / `Component` / `Page` / `Suite` (Pydantic v2 models)
**Responsibility**: validated, immutable-ish records of the site configuration.
**Algorithm**:
```
1. Define as BaseModel; fields typed (str, int, float, list[T], T | None).
2. Action: model_validator converts short YAML form → (kind, target, value) per per-kind rules.
3. Page: model_validator rejects duplicate Component.name within components.
4. Numeric ranges validated by the models: threshold float in (0..1), tolerance float in
   (0..100] — suite defaults and per-component overrides alike; Viewport.width/height
   positive ints; viewports non-empty (a component with no viewport silently never captured).
5. load_config: read suite.yml → Suite meta; walk pages/*/ → Page+Component; validate; return Suite.
```
**Errors**: `pydantic.ValidationError` (human-readable) on bad types/dups/out-of-range numerics/empty viewports; `FileNotFoundError` on missing files.
**Edge cases**: empty `pages/` → `Suite` with `pages=[]` (runner no-ops); `suite.yml` path vs folder path both accepted.

### `ComparisonResult`
**Responsibility**: verdict of one comparison.
**Algorithm**: pure record `(passed, mismatch_percent, diff_path)`.

### `compare`
**Responsibility**: pixelmatch two PNGs, decide pass/fail.
**Algorithm**:
```
1. baseline, current = Image.open(...).convert("RGBA") x2
2. IF baseline.size != current.size: return ComparisonResult(False, 100.0, None)
3. diff = Image.new("RGBA", baseline.size)
4. mismatched = pixelmatch(baseline, current, diff, threshold, includeAA=True)
5. pct = mismatched / (w*h) * 100; passed = pct <= tolerance
6. IF not passed: diff.save(diff_path); return ComparisonResult(False, pct, diff_path)
   ELSE: return ComparisonResult(True, pct, None)
```
**Errors**: `Image.open` raises on corrupt/missing PNG (caller guarantees existence).
**Edge cases**: identical images → 0% → passed, no diff written; size change → 100% failed, no diff.

### `Outcome`
**Responsibility**: one reportable result. Record `(suite, page, name, viewport, status, mismatch_percent: float | None, baseline_path, current_path, diff_path, error)`; `mismatch_percent` is `None` for BROKEN — no comparison happened, never a fake `0.0`.

### `write_results`
**Responsibility**: turn outcomes into Allure JSON + attachments.
**Algorithm**:
```
0. mkdir results_dir (parents, exist_ok)
1. for outcome in outcomes:
     case_id = f"peeksy::{outcome.suite}::{outcome.page}::{outcome.name}[{outcome.viewport}]"
     name    = f"{outcome.suite} / {outcome.page} / {outcome.name} [{outcome.viewport}]"
     attachments = [Attachment(copy_attachment(p), label) for p,label in
                    [(baseline_path,"baseline"),(current_path,"current"),(diff_path,"diff")]
                    if p is not None]
     status = {PASSED:Status.PASSED, FAILED:Status.FAILED, BROKEN:Status.BROKEN}[outcome.status]
     details = mismatch% if FAILED else (outcome.error if BROKEN else None)
     write <uuid>-result.json (TestResult)
```
**Errors**: copy_attachment raises on missing source (should not happen — runner only passes existing paths).
**Edge cases**: BROKEN with `current_path=None` → current attachment simply omitted; fresh (absent) `results_dir` → created by step 0.

### `build_report`
**Responsibility**: shell out to `allure` CLI.
**Algorithm**:
```
1. IF shutil.which("allure") is None: raise RuntimeError("allure CLI not found; install via brew/sdkman (requires JDK)")
2. subprocess.run(["allure","generate",results_dir,"--clean","-o",report_dir], check=True, capture_output=True)
```
**Errors**: missing CLI → human-readable error; `allure` non-zero → `CalledProcessError`.

### `CaptureSession`
**Responsibility**: Playwright lifecycle + deterministic capture.
**Algorithm (open_page)**:
```
1. page.set_viewport_size({width,height})
2. page.goto(url, wait_until=page.wait_until)   # networkidle | domcontentloaded | load
3. page.add_style_tag(content=ANIM_DISABLE_CSS); page.evaluate("document.fonts.ready")
4. run_actions(page, page.setup)
```
**Algorithm (capture_component)**:
```
1. run_actions(page, component.setup)
2. re-apply determinism: add_style_tag(ANIM_DISABLE_CSS); page.evaluate("document.fonts.ready")
   # open/reload inside setup navigated away and dropped the <style> from open_page
   # (deep-link flow: open_page injected it on a blank page)
3. loc = locate(page, component.selector)   # CSS | piercing (>> ) | frame_locator
   loc.first.wait_for(state="visible")      # page settled BEFORE masking
4. for sel in component.mask_selectors: locate(page, sel).evaluate("el => el.classList.add('peeksy-mask')")
   # a one-shot add_style_tag injects: .peeksy-mask{position:relative} .peeksy-mask::after{content:"";position:absolute;inset:0;background:#808080;z-index:99999}
5. loc.first.screenshot(type="png", path=out_path)
6. for sel in component.mask_selectors: locate(page, sel).evaluate("el => el.classList.remove('peeksy-mask')")
   # unmask AFTER the shot — the next capture on this page starts unmasked
7. return out_path
```
**Errors**: `playwright.sync_api.Error`/`TimeoutError` on nav/selector failures → propagate to runner → `BROKEN`.
**Edge cases**: shadow DOM / iframe components handled by the same `locate` helper.

### `run_test` / `run_generate`
**Responsibility**: orchestrate capture+compare+report over pages.
**Algorithm**: see Code Stack Trace. Both close the `CaptureSession` in a finally block; `generate` is fail-fast (first capture error propagates after teardown), `test` converts capture/baseline failures to BROKEN; per-page results subdirectories reset before the capture loop, prior `*-result.json`/`*-attachment` cleared before write; exit 0 iff all PASSED.

### `cli` commands
**Responsibility**: parse args, load config, delegate, exit code.
**Algorithm**: see Code Stack Trace. `test` raises `typer.Exit(code)`; never `sys.exit`.

---

## Cross-cutting Concerns

- **Error handling**: two tiers. (1) In `test`, capture/IO errors are caught in the runner and converted to `Outcome(status=BROKEN, error=...)` — never crash the run; in `generate`, the first capture error is fail-fast (session closed via finally, error propagates; resume with `--page`/`--component`). Both runners close the `CaptureSession` in a finally block. (2) Configuration errors (`pydantic.ValidationError`, `yaml.YAMLError` on syntactically broken YAML, `FileNotFoundError`/`NotADirectoryError` on a missing `--config` path) and the missing-allure-CLI surface as clear messages at the boundary (one app-level handler → `typer.Exit(1)`; `cli.report` prints an install hint + exits 1). `compare` size-mismatch → FAILED 100%, not an exception.
- **Determinism**: `device_scale_factor=1`; navigation wait strategy from `Page.wait_until` (default `networkidle`; `domcontentloaded` for live pages, confirmed by explicit `wait` actions); animations/transitions disabled via injected CSS; `document.fonts.ready`; masks via an opaque gray `::after` overlay (pixel-identical regardless of underlying content). Same `(Component, open page)` ⇒ pixelmatch-clean images.
- **Validation**: Pydantic at the boundary (`load_config`); per-page name uniqueness; numeric ranges enforced by the models — `threshold` ∈ (0..1), `tolerance` ∈ (0..100] (suite defaults and component overrides alike), `Viewport.width/height` positive, `viewports` non-empty; effective `threshold`/`tolerance` resolved in the runner (`component ?? suite`).
- **Logging**: minimal stdout — `test` prints a one-line summary; capture/compare are silent (Allure carries detail). No structured logging yet (deferred).
- **Caching**: none (baselines are read-only PNGs on disk).
- **Concurrency**: single-threaded; one browser/context reused. No concurrency requirements in scope.
- **Exit codes**: `test` → `0` all PASSED else `1` (CI-friendly), via `typer.Exit`.

---

## Usages Analysis

### `pydantic_config` (config, inline)
- **What**: Pydantic v2 model rules + short-form action parsing + per-page uniqueness.
- **Where used**: `Viewport`, `Action`, `Component`, `Page`, `Suite`, `load_config`.
- **Why**: single validation boundary; immutable-ish records; readable errors.
- **How**: `BaseModel` + `model_validator`; `yaml.safe_load` → model validation.

### `image_diff` (compare, `.goga/usages/cooks/image-diff.md`)
- **What**: pixelmatch + Pillow compare routine, threshold/tolerance model, diff-overlay.
- **Where used**: `compare`, `ComparisonResult`.
- **Why**: AA-aware mismatch counting + diff overlay in one call.
- **How**: `Image.open().convert("RGBA")`; `pixelmatch(baseline, current, diff, threshold, includeAA=True)`.

### `allure` (reporting, `.goga/usages/cooks/allure.md`)
- **What**: Allure result model, attachment handling, external `allure` CLI.
- **Where used**: `Outcome`, `write_results`, `build_report`.
- **Why**: one result per (page,component,viewport); stable `historyId`; browsable HTML.
- **How**: `allure_commons.model2.TestResult/Attachment/Status`; `subprocess` for `allure generate`.

### `playwright` (capture, `.goga/usages/cooks/playwright.md`)
- **What**: Playwright sync lifecycle, capture routine, masking, action execution (incl. `open`).
- **Where used**: `CaptureSession`.
- **Why**: true element screenshots, auto-wait, deterministic render.
- **How**: `sync_playwright`; one browser+context (DPR=1); `locator.screenshot`; `run_actions` dispatch by `kind`.

### `run_policy` (runner, inline)
- **What**: orchestration rules — generate/test semantics, BROKEN handling, page-namespaced paths, capture grouping, results-dir clearing.
- **Where used**: `run_generate`, `run_test`, `run_report`.
- **Why**: central place for path conventions + status policy.
- **How**: applied as numbered algorithm steps in the routines.

### `typer` (cli, inline)
- **What**: Typer command definitions, repeatable `--page`/`--component`, `typer.Exit`.
- **Where used**: `generate`, `test`, `report`, `main`.
- **Why**: thin facade; CI-friendly exit via `typer.Exit` (pytest-interceptable).
- **How**: `typer.Typer()` app; `Annotated[list[str] | None, typer.Option("--page")]`. `--config` (short `-c`) is declared as `Annotated[str, typer.Option("--config", "-c")]` with the default `"./peeksy.yml"` — the project-root suite file (convention: one repository = one site, `peeksy.yml` next to `pages/`). Path resolution: an explicitly passed `*.yml` path IS the suite file (any name); anything else is treated as the site folder (whose `suite.yml` is looked up). A missing default file surfaces through the app-level handler as a human-readable message (fix 8).

### Imported Usages
- None — each cell declares its own practices; `Imports.Usages` is unused (practices stay internal to their cells).

---

## `.usages/` Update

All six cell-level `.usages/*.md` already match the current CODEMANIFEST (verified during `goga-apply`).

### Cell: `peeksy/config`
- **`config.md`** → current. Covers `load_config`, page/component walk, short-form actions (incl. `open`), naming/uniqueness, paths. No additions needed.

### Cell: `peeksy/compare`
- **`compare.md`** → current. Covers `compare` call + verdict reading. No additions.

### Cell: `peeksy/reporting`
- **`reporting.md`** → current. Covers `write_results` (incl. BROKEN example) + `build_report`. No additions.

### Cell: `peeksy/capture`
- **`capture.md`** → current. Covers `open_page`/`capture_component` run loop (inline viewport union). No additions.

### Cell: `peeksy/runner`
- **`runner.md`** → current. Covers generate/test/report. No additions.

### Cell: `peeksy/cli`
- **`cli.md`** → current. Covers shell commands + flags. No additions.

No new `.usages/` files required.

---

## Test Stack Trace

### General Setup
- **Fixtures**: `tmp_path` for baseline/results/report dirs; a tiny local HTML fixture page served via `pytest-playwright` (or `file://`) with a stable component + a dynamic (timestamp) region to mask.
- **Deps under test**: `peeksy.config`, `peeksy.compare`, `peeksy.reporting`, `peeksy.capture` (Playwright, Chromium installed), `peeksy.runner`, `peeksy.cli`.
- **Allure CLI**: `report` tests stub `shutil.which`/`subprocess.run` to avoid the JDK dependency in unit tests.

### Source File Registry
- `peeksy/config/{models,loader}.py`, `peeksy/compare/{compare,result}.py`, `peeksy/reporting/{outcome,writer,report}.py`, `peeksy/capture/session.py`, `peeksy/runner/runner.py`, `peeksy/cli/app.py`.

---

### Positive Tests

#### `test_load_config_builds_suite_from_site_folder`
**Setup**: `tmp_path/sites/example.com/suite.yml` (name, paths, threshold=0.1, tolerance=0.5); `pages/home/page.yml` (url, setup: `[click: "#cookie"]`); `pages/home/header.yml` (selector, viewports `[{1280,720}]`).
**Input**: `load_config("tmp_path/sites/example.com")`.
**Trace**:
```
load_config(".../example.com")
  → resolve site dir
  → read suite.yml → Suite(name=..., threshold=0.1, tolerance=0.5)
  → walk pages/home → Page(name="home", url=..., setup=[Action(click,"#cookie",None)])
  → discover header.yml → Component(name="header", selector=..., viewports=[1280x720])
  → model_validator: names unique within page → ok
  → return Suite
```
**Assertions**:
```
suite.pages[0].name == "home"
suite.pages[0].components[0].name == "header"
suite.pages[0].components[0].viewports[0].width == 1280
suite.tolerance == 0.5
```
**Sufficiency**: proves site-folder discovery, filename→name derivation, and short-form action parsing.

#### `test_load_config_resolves_relative_paths_against_site_folder`
**Setup**: site at `tmp_path/sites/example.com` with relative `baseline_path: baselines`, `results_path: results`, `report_path: report` in suite.yml; `monkeypatch.chdir(tmp_path / "elsewhere")` — CWD is NOT the site folder.
**Input**: `load_config(str(tmp_path / "sites/example.com"))`.
**Trace**: `→ site dir resolved from the path → suite.yml read → relative paths normalized to absolute against the SITE folder → Suite built`.
**Assertions**: `suite.baseline_path == str(tmp_path / "sites/example.com/baselines")` (absolute, site-anchored, not CWD); same anchoring for `results_path` and `report_path`.
**Sufficiency**: catches a CWD-resolution regression — paths resolved against the CWD silently break generate/test when peeksy is invoked from another directory (empty baselines / stray BROKEN outcomes).

#### `test_compare_passes_on_identical_images`
**Setup**: write two byte-identical PNGs to `tmp_path`.
**Input**: `compare(baseline, current, diff_dir, threshold=0.1, tolerance=0.5)`.
**Trace**:
```
compare(b,c,d,0.1,0.5)
  → Image.open x2 .convert RGBA  (sizes equal)
  → pixelmatch → mismatched=0
  → pct=0.0; passed=True
  → return ComparisonResult(True, 0.0, None)
```
**Assertions**: `result.passed is True`; `result.mismatch_percent == 0.0`; `result.diff_path is None`; no diff file written.
**Sufficiency**: guards the happy path and the "no diff when passed" rule.

#### `test_run_generate_then_test_passes`
**Setup**: local fixture page; `Suite` with one component at 1280x720; baseline dir under `tmp_path`.
**Input**: `run_generate(suite,None,None)` then `run_test(suite,None,None)`.
**Trace**:
```
run_generate → CaptureSession.open → open_page → capture_component → baseline PNG written → close
run_test → open → open_page → capture_component → current PNG → compare(baseline,current) → passed → Outcome(PASSED)
        → clear results → write_results → return 0
```
**Assertions**: `exit_code == 0`; one `*-result.json` in `results_path`; baseline file exists at `{baseline_path}/home/header_1280x720.png`.
**Sufficiency**: end-to-end generate→test→Allure happy path.

#### `test_generate_and_test_honor_page_component_filters`
**Setup**: fixture site with 2 pages (`home`, `about`), each with 2 components (`header`, `sidebar`), one viewport each; baseline dir under `tmp_path`.
**Input**: `run_generate(suite, pages=["home"], components=["header"])`, then `run_test(suite, pages=["home"], components=["header"])`.
**Trace**:
```
run_generate → filter keeps only home/header → CaptureSession.open (non-empty filter → no early exit)
  → open_page(home, vp) once → capture_component(header) → exactly 1 baseline PNG
run_test → same filter → 1 capture → compare vs the single baseline → Outcome(PASSED)
  → clear results (pattern-only) → write_results → 1 result JSON → exit 0
```
**Assertions**: `len(list(baseline_dir.rglob("*.png"))) == 1`; `home/header_{WxH}.png` exists; `home/sidebar_*.png` and `about/**` baselines absent; `run_test` returns `0`; exactly one `*-result.json` in `results_path`.
**Sufficiency**: catches filter-ignored regressions, AND-semantics of both filters, and `None ⇒ all` mix-ups; covers the filtering acceptance criteria for `generate` and `test`.

#### `test_cli_test_exits_nonzero_on_regression`
**Setup**: local fixture page (`tmp_path/index.html` served over `file://` or a local HTTP server) with a component `#header`; `Suite` tolerance=0.5. Step 1: run `generate` against the original HTML. Step 2 (the mutation — survives page reloads): rewrite the HTML file on disk, adding `style="transform: translateY(2px)"` to `#header`.
**Input**: `CliRunner().invoke(app, ["test","--config",site])` after the rewrite.
**Trace**:
```
cli.test → load_config → run_test → open_page(same URL; HTML now shifted on disk)
         → capture_component → current PNG shifted ~2px
         → compare → mismatch% (edge pixels) > tolerance 0.5 → Outcome(FAILED)
         → write_results → exit_code=1 → typer.Exit(code=1)
```
**Assertions**: `result.exit_code == 1`; summary line printed; `*-result.json` has `"status": "failed"` with mismatch in `statusDetails`; diff attachment file exists in `results_path`.
**Sufficiency**: reproduces the acceptance criterion "a real ~2px shift is FAILED" — the mutation lives on disk, so it survives `open_page` reloading the URL between generate and test.

---

#### `test_regression_in_single_viewport_fails_only_that_result`
**Setup**: fixture page; `Component` with 2 viewports (1280x720, 375x667); baseline captured for both; then the HTML is rewritten on disk with a shift applied ONLY via a mobile media query (`@media (max-width: 500px) { #header { transform: translateY(2px); } }`).
**Input**: `run_test(suite, None, None)`.
**Trace**:
```
run_test → ordered viewport dedupe [1280x720, 375x667] → open_page per viewport
  → 1280x720: media query not matched → capture identical → PASSED
  → 375x667: media query matched → shifted capture → compare → FAILED
  → 2 Outcomes → clear results (patterns) → write_results → 2 result JSONs → exit 1
```
**Assertions**: `exit_code == 1`; exactly 2 `*-result.json`; one with `"passed"`, one with `"failed"`; the FAILED `statusDetails` carries the mismatch; baseline filenames differ as `_1280x720.png` / `_375x667.png` (no WxH collision).
**Sufficiency**: covers the acceptance criterion "only the regressing viewport row is FAILED" + the baseline naming pattern + viewport dedupe (regression of the ordered-dedupe fix); the two results carry distinct `historyId`s (`…::header[1280x720]` vs `…::header[375x667]`) so Allure history keeps both rows.

### Negative Tests

#### `test_load_config_rejects_invalid_page_and_action_shapes`
**Setup**: `pytest.mark.parametrize` over 8 invalid sites built in `tmp_path`, each with exactly one violation: (1) `wait_until: eager` in page.yml; (2) `url: null` with setup NOT starting with `open`; (3) a set `url` with setup starting with `open`; (4) `- fill: "#search"` (a bare string instead of `[target, value]`); (5) `threshold: 5` in suite.yml (outside (0..1)); (6) `tolerance: 150` in suite.yml (outside (0..100]); (7) `viewports: []` in header.yml (empty list — the component would silently never be captured); (8) `viewports: [{width: 0, height: 720}]` in header.yml (non-positive dimension).
**Input**: `load_config(site)` per case.
**Trace**: `→ file walk → Pydantic validation → the responsible model_validator or range constraint detects the violation → ValidationError raised (no Playwright involved)`.
**Assertions**: `pytest.raises(ValidationError)`; the message mentions the offending field (`wait_until` / `open` / `fill` / `threshold` / `tolerance` / `viewports`).
**Sufficiency**: pins all three contract validators (wait_until enum, url⇄open exclusivity both ways, short-form action rules) — without them an invalid config reaches capture and fails as a confusing Playwright runtime error instead of a config error. Cases 5–8 pin the range validation: without it an out-of-range `threshold` goes straight to pixelmatch, a `tolerance` above 100 makes any diff PASSED, and empty/non-positive viewports silently drop components from the run.

#### `test_load_config_rejects_duplicate_component_name_within_page`
**Setup**: `pages/home/header.yml` and a second `pages/home/header.yml`-named file (different content, same derived name).
**Input**: `load_config(site)`.
**Trace**: `… → model_validator detects duplicate "header" → ValidationError`.
**Assertions**: raises `ValidationError`; message mentions the duplicate name and page.
**Sufficiency**: enforces per-page uniqueness (prevents silent baseline/testCaseId collision).

#### `test_run_test_page_setup_failure_marks_all_components_broken`
**Setup**: site with 2 pages; `home` points to a dead URL (`file:///nonexistent-page.html`), `about` to a working fixture; one component per page.
**Input**: `run_test(suite, None, None)`.
**Trace**:
```
run_test → open_page(home) raises (goto file-not-found)
  → except → Outcome(BROKEN, error="page setup failed: …", current_path=None) for home/header
  → continue → open_page(about) OK → capture → compare → Outcome(PASSED)
  → close session (finally) → clear results → write_results → 2 result JSONs → exit 1
```
**Assertions**: `exit_code == 1`; 2 `*-result.json`; the home result is `"broken"` with `error` containing "page setup failed" and NO current attachment; the about result is `"passed"` (the run continued past the dead page).
**Sufficiency**: covers the infrastructure-error acceptance criterion, the run-continues-after-page-failure policy, and the BROKEN outcome shape from a page-level failure.

#### `test_run_test_missing_baseline_is_broken`
**Setup**: a component in config with no baseline generated.
**Input**: `run_test(suite,None,None)`.
**Trace**:
```
… → capture_component → current OK → baseline file missing
  → Outcome(BROKEN, error="baseline not found; run `peeksy generate`", current_path=None, mismatch_percent=None)
  → write_results (omits current attachment) → return 1
```
**Assertions**: `exit_code == 1`; BROKEN outcome in results; `error` contains "baseline not found"; `mismatch_percent is None`.
**Sufficiency**: missing baseline is infrastructure failure, not a visual regression.

#### `test_build_report_missing_allure_raises_human_readable`
**Setup**: monkeypatch `shutil.which("allure") → None`.
**Input**: `build_report(results, report)`.
**Trace**: `→ shutil.which None → raise RuntimeError("allure CLI not found…")`.
**Assertions**: raises with install hint; no `subprocess`/`FileNotFoundError`.
**Sufficiency**: clean error path when JDK/allure absent.

#### `test_build_report_invokes_allure_with_canonical_args`
**Setup**: monkeypatch `shutil.which` → `"/usr/bin/allure"`; monkeypatch `subprocess.run` with a recording spy (returns a completed-process stub).
**Input**: `build_report("/tmp/results", "/tmp/report")`.
**Trace**: `→ which OK → spy called once with the canonical argv`.
**Assertions**: spy called exactly once; `args == ["allure", "generate", "/tmp/results", "--clean", "-o", "/tmp/report"]` (positional results dir first); `check is True`.
**Sufficiency**: pins the canonical `allure generate` argument order and the `--clean` flag without requiring a JDK; catches swapped-results/report-dir regressions.

#### `test_cli_report_prints_install_hint_when_allure_absent`
**Setup**: monkeypatch `shutil.which → None`.
**Input**: `CliRunner().invoke(app, ["report","--config",site])`.
**Assertions**: `exit_code == 1`; stdout contains "allure"; no Python traceback.
**Sufficiency**: the `report` command degrades gracefully without allure.

---

### Edge Case Tests

#### `test_compare_tolerance_boundary_semantics`
**Setup**: synthetic PNGs via PIL (no browser): a 100x100 baseline of solid color and a current image with exactly 1% of pixels altered (100 pixels).
**Input**: `compare(baseline, current, diff_dir, threshold=0.1, tolerance=1.0)` (mismatch exactly == tolerance), then `tolerance=0.99` (mismatch above).
**Trace**: `→ pixelmatch counts ~1.0% mismatch → passed = 1.0 <= 1.0 → True; with 0.99 → False → diff written`.
**Assertions**: case 1: `passed is True`, `diff_path is None`; case 2: `passed is False`, `diff_path` exists.
**Sufficiency**: pins the non-strict `<=` acceptance semantics on deterministic data (a `<` regression would flip case 1); pairs with the filter test asserting a component-level `tolerance` override is used over the suite default.

#### `test_compare_size_change_is_definite_failure`
**Setup**: baseline 1280x720 PNG; current 1280x800 PNG.
**Input**: `compare(...)`.
**Assertions**: `result.passed is False`; `result.mismatch_percent == 100.0`; `result.diff_path is None`.
**Sufficiency**: size change never crashes pixelmatch; reported as 100% regression.

#### `test_results_dir_cleared_between_test_runs`
**Setup**: run `test` twice (second run after a state change).
**Input**: two `run_test` invocations.
**Assertions**: after the second run, the count of `*-result.json` equals the number of current outcomes (no leftovers from run 1).
**Sufficiency**: consecutive runs never silently mix.

#### `test_run_test_empty_selection_is_noop_preserving_results`
**Setup**: fixture site with 1 page / 1 component; run `run_test(suite, None, None)` once to produce results (≥1 `*-result.json` in `results_path`); record the JSON count; monkeypatch `peeksy.capture.session.CaptureSession.open` to raise AssertionError("session must not open on a no-op run") if called.
**Input**: `run_test(suite, pages=["nonexistent"], components=None)`.
**Trace**: `→ filter keeps nothing → early return 0 BEFORE the per-page subdirectory reset (step 2.5), before CaptureSession.open (patched — not called), before the clear patterns, before write_results → results dir untouched`.
**Assertions**: `exit_code == 0`; the patched `CaptureSession.open` was not called; the count of `*-result.json` in `results_path` is unchanged from the recorded value.
**Sufficiency**: catches three regressions at once — launching a browser for a no-op run (slow, breaks offline testing), wiping prior results on an empty filter (a typo in `--page` would silently destroy the previous report), and writing an empty outcome set (the report "disappears").

#### `test_open_action_navigates_mid_setup`
**Setup**: a page whose `setup` is `[open: "https://example.com/deep", click: "#x"]`.
**Input**: `run_generate` (capture).
**Trace**: `open_page → run_actions → open: page.goto(value, wait_until=wait_strategy) → click … → capture_component`.
**Assertions**: capture succeeds; Playwright `page.goto` called with the deep URL (assert via spy/mock).
**Sufficiency**: the `open` kind routes through `run_actions` like other kinds.

#### `test_masked_dynamic_region_stable_and_no_mask_leakage`
**Setup**: fixture page with component `#header` containing `<span class="timestamp">` (JS writes `Date.now()` into it on load) and a second component `#footer` (no masks); `header.mask_selectors = [".timestamp"]`; PIL available for pixel checks.
**Input**: `run_generate` then `run_test` (the timestamp differs between the two runs).
**Trace**:
```
generate → capture header: wait_for(#header) → mask .timestamp (opaque gray ::after) → shot → unmask
         → capture footer immediately after: starts unmasked → shot
test     → timestamp re-randomized on reload → same mask flow → both compares pixel-stable
```
**Assertions**: both outcomes `"passed"` (`mismatch_percent <= tolerance`); in the footer PNG there are NO pixels of the exact mask gray `#808080` (PIL scan) — proving the mask did not leak onto the next component's shot.
**Sufficiency**: catches both regressions — a broken mask (dynamic-zone flake → FAILED header) and mask leakage (missing unmask → gray pixels on footer).

#### `test_capture_is_idempotent_pixelmatch_clean`
**Setup**: capture the same component twice back-to-back.
**Input**: `compare(baseline_from_run1, current_from_run2, ...)`.
**Assertions**: `result.passed is True`; `mismatch_percent == 0.0`.
**Sufficiency**: guarantees deterministic capture (anti-flake).

---

## Additional Instructions for the Implementation Agent

- Implement leaves→root: `config` → `compare` + `reporting` → `capture` → `runner` → `cli`. Each cell is a Python package with `__init__.py` exposing its full API via `__all__`.
- Pin exact versions of `pixelmatch==0.4.0`, `playwright`, `allure-python-commons`, `typer`, `pydantic` in `pyproject.toml` (managed by `uv`); run `playwright install chromium`. **pixelmatch import**: the PIL-aware entry point is `from pixelmatch.contrib.PIL import pixelmatch` (NOT the top-level module, which works on raw RGBA arrays) — verified against the PyPI package README (v0.4.0, 2026-03); re-check the one-liner import once at implementation time.
- **Playwright version = Chromium build (risk 1b)**: pin `playwright` to an exact version (`==`, never `>=`). A Chromium update changes pixel-level rendering and silently invalidates ALL baselines at once. On any `playwright` upgrade, re-run `peeksy generate` to re-create baselines before running `test`.
- **Single render environment (risk 1c)**: capture baselines and run `test` in the SAME OS/font environment — a pinned Docker image used both locally and in CI, or generate baselines on CI itself. macOS vs Linux differ in font anti-aliasing; masking cannot fix text-rendering differences.
- **locale/timezone intentionally not fixed (risk 1a — accepted trade-off)**: the overlay-only masking model relies on the config author listing every dynamic region (dates, times, counters, ads) in `mask_selectors`; unmasked dynamic zones may flake across environments. Do not add locale/timezone pinning without revisiting this decision.
- **Allure CLI (JDK) — accepted optional dependency**: `generate`/`test` are fully autonomous (results JSON + exit code, no Java); only `report` shells out to `allure` and degrades with a human-readable install hint when absent. A pure-Python report renderer is a noted future alternative, not MVP scope.
- `Action` short-form parsing lives in `config` (`load_config`), not in `capture`. `capture` only executes `Action` by `kind` via the `run_actions` helper from `playwright.md`.
- Baseline paths are page-namespaced: `{baseline_path}/{page}/{name}_{WxH}.png`. Never flatten to a single dir.
- `test` must clear `results_path` before `write_results` — ONLY by exact patterns `*-result.json` and `*-attachment` (prior-run artifacts); never wipe the whole directory (current-run `.current.png`/`.diff.png` files must survive). Additionally, BEFORE the capture loop, remove the nested `{results_path}/{page}/` subdirectories — stale `.current.png`/`.diff.png` of renamed/removed components are never matched by the patterns and would accumulate forever; the current run re-creates the subdirectories.
- `--config` (short `-c`) is a Typer option (`Annotated[str, typer.Option("--config", "-c")]`) with the default `"./peeksy.yml"` — the project-root suite file (one repository = one site). An explicitly passed `*.yml` path is treated as the suite file directly (any filename); a folder argument falls back to looking up `suite.yml` inside it.
- Never use `sys.exit` in CLI — always `raise typer.Exit(code=...)`.
- Register ONE app-level Typer exception handler for configuration errors from `load_config`: `(pydantic.ValidationError, yaml.YAMLError, FileNotFoundError, NotADirectoryError)` — print the message human-readably (no traceback) and `typer.Exit(code=1)` — shared by `generate`/`test`/`report`.
- Keep Playwright inside `capture` only; `runner` depends on `CaptureSession`, never on Playwright types.
- Re-apply the determinism CSS (animation-disable + fonts) in `capture_component` AFTER the component setup actions — `open`/`reload` actions navigate away and drop the `<style>` injected by `open_page` (deep-link flow injects it on a blank page); without the re-inject, `- reload: {}` components and deep-link pages are captured with active animations (flaky diffs).
- Mask via an opaque gray `::after` overlay (never `display:none`); the `locate` helper supports plain CSS, piercing selectors (`>>`), and `frame_locator` — and is used for BOTH the component selector and every mask selector.
- Follow `peeksy/*/CODEMANIFEST` as the authoritative contract; `docs/arch/peeksy-cli.md` is the mirror.
