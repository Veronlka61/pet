# Plan: `peeksy-cli`

Result of compiling `docs/design/peeksy-cli.md` into ralphex-executable tasks.
Source contract: the six `peeksy/*/CODEMANIFEST` files (read-only, authoritative).

---

## Purpose

Implement the peeksy visual-regression CLI from scratch (greenfield). After this plan completes,
the `peeksy` console command provides `generate` / `test` / `report`:

- `generate` captures deterministic Playwright baselines per (page, component, viewport),
- `test` re-captures, compares via pixelmatch against baselines, writes Allure results,
  and exits non-zero on any regression or infrastructure failure,
- `report` builds the browsable Allure HTML report.

Every cell currently contains only `CODEMANIFEST` + `.usages/` — no Python code, no `__init__.py`,
no `pyproject.toml`, no tests. Strategy: implement leaves → root
(`config` → `compare` + `reporting` → `capture` → `runner` → `cli`), one cell fully before the next,
strict TDD per task (contract tests → code → logic tests → debug → re-verify → lint).

---

## Context

### Contract Surface

**Cell `peeksy/config`** (manifest: `peeksy/config/CODEMANIFEST`, inline usage `pydantic_config`)

**Entity: `Viewport`** — Type: class (`BaseModel`); location `models.py`; facade: importable from `peeksy.config`.
- Properties: `width -> int` (CSS px, positive), `height -> int` (CSS px, positive).

**Entity: `Action`** — Type: class; location `models.py`; facade: importable from `peeksy.config`.
- Properties: `kind -> str` (one of click, hover, scroll_to, scroll_by, fill, press, select, wait, open, reload),
  `target -> str | None` (CSS selector; None when no element needed),
  `value -> str | None` (aux value: fill/press/select text/key/option, scroll_by px, wait ms-or-mode, open URL).
- Data only — carries no behavior; executed by the capture cell. Short YAML form is parsed into this
  model by `load_config` per per-kind rules (see `pydantic_config` in the manifest).

**Entity: `Component`** — Type: class; location `models.py`; facade: importable from `peeksy.config`.
- Properties: `name -> str` (from filename, unique within page), `selector -> str`,
  `mask_selectors -> list[str]`, `viewports -> list[Viewport]` (non-empty),
  `threshold -> float | None` (override in (0..1)), `tolerance -> float | None` (override in (0..100]),
  `setup -> list[Action]`.

**Entity: `Page`** — Type: class; location `models.py`; facade: importable from `peeksy.config`.
- Properties: `name -> str` (from folder name), `url -> str | None` (None ⇒ deep-link flow: setup[0] is `open`),
  `wait_until -> str` (networkidle default | domcontentloaded | load), `setup -> list[Action]`,
  `components -> list[Component]` (name-sorted for deterministic capture order).
- Validators: unique `Component.name` within the page; `wait_until` enum; url⇄leading-open mutual exclusivity
  (both directions).

**Entity: `Suite`** — Type: class; location `models.py`; facade: importable from `peeksy.config`.
- Properties: `name -> str`, `pages -> list[Page]`, `baseline_path -> str`, `results_path -> str`,
  `report_path -> str`, `threshold -> float` (0..1), `tolerance -> float` (0..100]).
- Same component name MAY repeat across pages (namespaced by page).

**Routine: `load_config`** — signature `load_config(path: str) -> suite: Suite`; location `loader.py`;
facade: importable from `peeksy.config`. Algorithm: resolve site folder (explicit `*.yml` IS the suite
file → parent; folder → `suite.yml` inside) → read+validate suite meta, normalize relative paths against
the site folder → walk `pages/*/` (`page.yml` + sibling component `*.yml`) → build/validate models →
return `Suite`.

**Cell `peeksy/compare`** (manifest: `peeksy/compare/CODEMANIFEST`, usage `image_diff` → `.goga/usages/cooks/image-diff.md`)

**Entity: `ComparisonResult`** — Type: class (pure record); location `result.py`; facade: importable from `peeksy.compare`.
- Properties: `passed -> bool`, `mismatch_percent -> float` (0..100), `diff_path -> str | None`
  (None when passed — no diff written).

**Routine: `compare`** — signature `compare(baseline: str, current: str, diff_dir: str, threshold: float, tolerance: float) -> result: ComparisonResult`;
location `compare.py`; facade: importable from `peeksy.compare`. Algorithm: open both PNGs as RGBA →
size mismatch ⇒ `ComparisonResult(False, 100.0, None)` → pixelmatch (threshold, includeAA=True) →
`passed = mismatch_percent <= tolerance` → save diff into `diff_dir` only when not passed.

**Cell `peeksy/reporting`** (manifest: `peeksy/reporting/CODEMANIFEST`, usage `allure` → `.goga/usages/cooks/allure.md`)

**Entity: `Outcome`** — Type: class (record); location `outcome.py`; facade: importable from `peeksy.reporting`.
- Properties: `suite -> str`, `page -> str`, `name -> str`, `viewport -> str` (e.g. "1280x720"),
  `status -> str` ("PASSED" | "FAILED" | "BROKEN"), `mismatch_percent -> float | None` (None for BROKEN —
  never a fake 0.0), `baseline_path -> str | None`, `current_path -> str | None`, `diff_path -> str | None`,
  `error -> str | None`.

**Routine: `write_results`** — signature `write_results(outcomes: list[Outcome], results_dir: str)`;
location `writer.py`; facade: importable from `peeksy.reporting`. One `<uuid>-result.json` per Outcome;
`testCaseId`/`historyId` = `peeksy::{suite}::{page}::{name}[{viewport}]`; display name
`{suite} / {page} / {name} [{viewport}]`; Allure suite label = `Outcome.suite`; attachments copied only
for non-None paths; statusDetails: mismatch % when FAILED, error when BROKEN. Does NOT clear prior
artifacts (caller's responsibility).

**Routine: `build_report`** — signature `build_report(results_dir: str, report_dir: str)`;
location `report.py`; facade: importable from `peeksy.reporting`. `shutil.which("allure")` guard →
human-readable error; else invoke the allure CLI with `check=True, capture_output=True`.

**Cell `peeksy/capture`** (manifest: `peeksy/capture/CODEMANIFEST`; Imports: `Component`, `Viewport`, `Page`, `Action` from `peeksy/config`; usage `playwright` → `.goga/usages/cooks/playwright.md`)

**Entity: `CaptureSession`** — Type: class; location `session.py`; facade: importable from `peeksy.capture`.
- Methods: `open()` (headless Chromium, one context DPR=1, one page),
  `open_page(page: Page, viewport: Viewport)` (set viewport → goto if url set → determinism CSS + fonts →
  run page setup), `capture_component(component: Component, out_path: str) -> png_path: str`
  (component setup → RE-apply determinism → mask overlays → wait visible → screenshot → unmask),
  `close()` (teardown).
- Constraint: idempotent captures — same Component on same open page ⇒ pixelmatch-clean images.

**Cell `peeksy/runner`** (manifest: `peeksy/runner/CODEMANIFEST`; Imports: `Suite`, `Page`, `Component`, `Viewport` from `peeksy/config`; `CaptureSession` from `peeksy/capture`; `compare`, `ComparisonResult` from `peeksy/compare`; `Outcome`, `write_results`, `build_report` from `peeksy/reporting`; inline usage `run_policy`)

**Routine: `run_generate`** — signature `run_generate(suite: Suite, pages: list[str] | None, components: list[str] | None)`;
location `runner.py`; facade: importable from `peeksy.runner`. Fail-fast baseline capture, session closed
in finally, no browser launch on an empty filter result.

**Routine: `run_test`** — signature `run_test(suite: Suite, pages: list[str] | None, components: list[str] | None) -> exit_code: int`;
location `runner.py`; facade: importable from `peeksy.runner`. BROKEN semantics for capture/baseline
failures; per-page results subdirs reset before the loop; prior `*-result.json`/`*-attachment` cleared
before write; exit 0 iff all PASSED.

**Routine: `run_report`** — signature `run_report(suite: Suite)`;
location `runner.py`; facade: importable from `peeksy.runner`. Delegates to `build_report`.

**Cell `peeksy/cli`** (manifest: `peeksy/cli/CODEMANIFEST`; Imports: `load_config`, `Suite` from `peeksy/config`; `run_generate`, `run_test`, `run_report` from `peeksy/runner`; inline usage `typer`)

**Routines** (all location `app.py`, facade: importable from `peeksy.cli`):
- `generate(config: str, page: list[str] | None, component: list[str] | None)` — load config, delegate.
- `test(config: str, page: list[str] | None, component: list[str] | None)` — load, delegate, print
  one-line summary, `raise typer.Exit(code=exit_code)`.
- `report(config: str)` — load, delegate; missing-allure error → install hint + exit 1.
- `main()` — run the Typer app (console entry point).
- ONE app-level exception handler shared by all three commands:
  `(pydantic.ValidationError, yaml.YAMLError, FileNotFoundError, NotADirectoryError)` →
  human-readable message (no traceback) → `typer.Exit(code=1)`.

### Re-exports

None — no `->Name: {}` embedding blocks exist in any of the six manifests.

### Usages Context

- **`pydantic_config`** (config, inline in `peeksy/config/CODEMANIFEST`): Pydantic v2 model rules,
  site-folder discovery, short-form action parsing, per-page uniqueness, numeric ranges,
  CWD-independent path normalization. Read it directly from the manifest header.
- **`image_diff`** (compare, `.goga/usages/cooks/image-diff.md`): pixelmatch + Pillow routine,
  threshold/tolerance model, diff overlay. PIL-aware import:
  `from pixelmatch.contrib.PIL import pixelmatch` (NOT the top-level module).
- **`allure`** (reporting, `.goga/usages/cooks/allure.md`): Allure result model
  (`allure_commons.model2.TestResult/Attachment/Status/StatusDetails/Label`), attachment conventions,
  external allure CLI.
- **`playwright`** (capture, `.goga/usages/cooks/playwright.md`): sync lifecycle, capture routine,
  masking overlay, `run_actions` dispatch table per `kind`, viewport handling, failure modes.
- **`run_policy`** (runner, inline in `peeksy/runner/CODEMANIFEST`): orchestration rules — generate/test
  semantics, BROKEN handling, page-namespaced paths, capture grouping, results-dir clearing.
- **`typer`** (cli, inline in `peeksy/cli/CODEMANIFEST`): command definitions, repeatable
  `--page`/`--component`, `--config/-c` default `./peeksy.yml`, `typer.Exit`, app-level handler.

### Imported Usages

None — `Imports.Usages` is unused in every manifest; practices stay internal to their cells.

### Local Usages

All six cell-level `.usages/*.md` files are current and match the CODEMANIFESTs (verified during
`goga-apply`). **No `.usages/` creation or update tasks are required.** For reference:
`peeksy/config/.usages/config.md`, `peeksy/compare/.usages/compare.md`,
`peeksy/reporting/.usages/reporting.md`, `peeksy/capture/.usages/capture.md`,
`peeksy/runner/.usages/runner.md`, `peeksy/cli/.usages/cli.md`.

### External Dependencies

- **Python packages** (pinned in `pyproject.toml`, managed by `uv`): `pydantic` (v2), `pyyaml`,
  `pixelmatch==0.4.0` (exact), `pillow`, `playwright` (exact `==` pin — never `>=`; a Chromium build
  change invalidates all baselines), `allure-python-commons`, `typer`.
- **Dev**: `pytest`, `ruff`.
- **System**: Chromium via `playwright install chromium` (Task 1). The `allure` CLI (JDK) is an
  OPTIONAL dependency — only `report` shells out to it; unit tests stub `shutil.which`/`subprocess.run`.
- **Tools**: `uv` for dependency management.

### Interaction Diagram (verbatim from the design document)

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

Data flows:
1. **generate**: `cli.generate → load_config(path) → Suite → run_generate(suite, pages, components) → CaptureSession.open → (per page,viewport: open_page → capture_component → baseline PNG) → CaptureSession.close`.
2. **test**: `cli.test → load_config → Suite → run_test → CaptureSession.open → (per page,viewport: open_page → capture_component → compare → Outcome) → clear results → write_results → exit_code → cli prints summary → typer.Exit(code)`.
3. **report**: `cli.report → load_config → Suite → run_report → build_report(results_path, report_path) → allure CLI`.

Initialization order (leaves first): `config` → (`compare`, `reporting`) → `capture` → `runner` → `cli`.

---

## Facts

- Greenfield: all six cells contain ONLY `CODEMANIFEST` + `.usages/`. No `__init__.py`, no `*.py` files,
  no `pyproject.toml`, no `tests/` directory.
- Language: Python. A cell = Python package; facade = `__init__.py` with `__all__`.
  PascalCase classes; snake_case functions/methods/properties; type hints mandatory.
  Allowed types: `str, int, float, bool, list[T], dict[str, T], T | None` (no `*args`/`**kwargs`,
  no bare `dict`/`list`).
- `Viewport` is a Pydantic model ⇒ unhashable ⇒ viewport dedupe in the runner MUST be an ordered
  list scan (first-seen), never a `set`.
- `Page.components` is name-sorted by the config layer — the runner relies on that ordering.
- Allure CLI argv pinned by the design (positional results dir FIRST — this overrides the example
  snippet in `.goga/usages/cooks/allure.md`):
  `["allure", "generate", <results_dir>, "--clean", "-o", <report_dir>]`.
- pixelmatch PIL-aware entry point: `from pixelmatch.contrib.PIL import pixelmatch`
  (verify once at implementation: `uv run python -c "from pixelmatch.contrib.PIL import pixelmatch"`).
- Mask gray is exactly `#808080`; the footer-no-leakage test scans for that exact pixel value.
- `root main.py` is leftover PyCharm boilerplate — out of scope, do not touch.
- Git: branch `Stage1`; working tree has uncommitted manifest/doc edits (expected — contract work).
- Acceptance-risk decisions from the design: playwright pinned exactly; single render environment
  (same OS/font for baselines and test); locale/timezone intentionally NOT fixed (masking model
  covers dynamic zones); allure CLI is an accepted optional dependency.

---

## Gap Analysis

- **Missing contract entities**: ALL — every entity/routine of all six cells (nothing is implemented).
- **Missing facade exposure**: all six `__init__.py` facades + root `peeksy/__init__.py`.
- **Missing project scaffolding**: no `pyproject.toml` (deps, `[project.scripts] peeksy = "peeksy.cli.app:main"`,
  pytest/ruff config), no `tests/`.
- **Missing tooling state**: Chromium not installed; no venv/lockfile.
- **Existing code that can be reused**: none (greenfield). Practices (`.goga/usages/cooks/*.md`) and
  cell `.usages/*.md` are complete and current — implementation guidance only, no doc tasks.
- **Test coverage gaps**: everything — ~60 test cases across 10 tasks (all 20 design scenarios).
- **No CODEMANIFEST changes needed** — the contract passed `goga-review-arch` + `goga lint` (0 errors).

---

## Tasks

> **Package ordering rule**: coding tasks for each cell are completed before starting the next.
> Within each coding task, contract tests are written first (TDD workflow).
> Order: `config` → `compare` → `reporting` → `capture` → `runner` → `cli` → integration.

### Task 1: Project scaffolding — pyproject, uv, tooling, root package (infrastructure)

This task creates the Python project skeleton every later task builds on. No contract entities are
implemented here — only build/test infrastructure. The project is managed by `uv`; dependencies come
from the design document's pinning policy. The root package `peeksy` becomes importable (empty facade).

**Usages relevant to this task:**
- `image_diff` (Setup section, `.goga/usages/cooks/image-diff.md`): `pixelmatch==0.4.0` + `pillow`; verify the import `from pixelmatch.contrib.PIL import pixelmatch` right after syncing.
- `playwright` (Setup section, `.goga/usages/cooks/playwright.md`): `uv add playwright` + `uv run playwright install chromium`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] Create `pyproject.toml` (uv-managed): `[project]` name `peeksy`, `requires-python = ">=3.10"`;
      runtime deps: `pydantic` (v2), `pyyaml`, `pixelmatch==0.4.0` (EXACT), `pillow`,
      `playwright` (EXACT `==` pin of the current version — never `>=`), `allure-python-commons`, `typer`;
      dev deps (`[dependency-groups]`): `pytest`, `ruff`
- [x] Add `[project.scripts]`: `peeksy = "peeksy.cli.app:main"` (resolves once Task 9 lands)
- [x] Add `[tool.pytest.ini_options]`: `testpaths = ["tests"]`; add `[tool.ruff]`:
      `target-version = "py310"`, `line-length = 100`
- [x] Create root package facade `peeksy/__init__.py` — docstring only, `__all__: list[str] = []`
- [x] Create empty `tests/` directory (no test files yet)
- [x] Run `uv sync` — resolves and installs all deps, creates `uv.lock`
- [x] Run `uv run python -c "from pixelmatch.contrib.PIL import pixelmatch"` — verifies the
      PIL-aware pixelmatch entry point; if it fails, fix the import source (do NOT proceed on a broken import)
- [x] Run `uv run playwright install chromium` — downloads the browser once for capture tests
- [x] Verify root package importable: `uv run python -c "import peeksy"` — exits 0
- [x] Verify test runner green (collects nothing): `uv run pytest` — exit 0
- [x] Lint: `uv run ruff check .` — fix formatting if necessary

### Task 2: `peeksy/config` — Pydantic models `Viewport`/`Action`/`Component`/`Page`/`Suite` (TDD)

Covers contract entities `Viewport`, `Action`, `Component`, `Page`, `Suite` — all at
`location: models.py` (one task per the same-location rule). Also creates the cell facade
`peeksy/config/__init__.py` exposing the five models via `__all__`.
Behavioral source: entity annotations + the header usage `pydantic_config` in
`peeksy/config/CODEMANIFEST` — read both before writing tests. Design algorithm (verbatim):

```
1. Define as BaseModel; fields typed (str, int, float, list[T], T | None).
2. Action: model_validator converts short YAML form → (kind, target, value) per per-kind rules.
3. Page: model_validator rejects duplicate Component.name within components.
4. Numeric ranges validated by the models: threshold float in (0..1), tolerance float in
   (0..100] — suite defaults and per-component overrides alike; Viewport.width/height
   positive ints; viewports non-empty (a component with no viewport silently never captured).
5. load_config: read suite.yml → Suite meta; walk pages/*/ → Page+Component; validate; return Suite.
```

(Step 5 belongs to Task 3 — here only the models + their validators.)

Per-kind argument rules for `Action` (from the manifest, binding): click/hover/scroll_to take
`target`; fill/select take `[target, value]`; press takes a key `value` (target optional);
scroll_by takes pixels `value` (or `[x, y]`); wait takes selector / {selector, hidden} / ms / nothing;
open takes a URL `value`, `target=None`; reload takes neither `target` nor `value`.
`kind` is a closed set (Literal): click, hover, scroll_to, scroll_by, fill, press, select, wait, open, reload.
`Page.wait_until` ∈ {networkidle, domcontentloaded, load}, default `networkidle`.
url⇄open exclusivity (Page model_validator, BOTH directions): `url=None` requires `setup[0].kind == "open"`;
a set `url` forbids `open` as `setup[0]`.
Components are stored name-sorted (Page validator or loader ordering — keep it inside the model so
the invariant holds for direct construction too).

**Usages relevant to this task:**
- `pydantic_config` (inline, `peeksy/config/CODEMANIFEST` header): all model rules — immutability where practical, ranges, uniqueness, wait_until enum, url⇄open exclusivity, name-sorted components.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests** (`tests/test_config_models.py`): all five classes importable from `peeksy.config`
      facade; constructor signatures match the entity signatures (`Viewport(width, height)`,
      `Action(kind, target, value)`, `Component(name, selector, mask_selectors, viewports, threshold, tolerance, setup)`,
      `Page(name, url, wait_until, setup, components)`,
      `Suite(name, pages, baseline_path, results_path, report_path, threshold, tolerance)`);
      properties readable with declared types (expected to fail now)
- [x] **Code**: create `peeksy/config/models.py` — five Pydantic v2 `BaseModel` classes with type hints
      per the contract signatures; defaults where the manifest implies them (`wait_until="networkidle"`,
      empty-list defaults for `setup`/`mask_selectors` are acceptable; `viewports` must remain required
      and non-empty)
- [x] **Code**: implement validators — `kind` Literal; threshold `gt=0, lt=1` and tolerance `gt=0, le=100`
      on both `Suite` and `Component`; `Viewport.width/height` positive ints (`gt=0`);
      `Component.viewports` non-empty (`min_length=1`); `Page`: duplicate `Component.name` rejected,
      `wait_until` Literal, url⇄leading-open mutual exclusivity both directions; `Page.components`
      name-sorted on validation
- [x] **Code**: create cell facade `peeksy/config/__init__.py` — import and re-export `Viewport`,
      `Action`, `Component`, `Page`, `Suite` via `__all__`
- [x] **Interface verification**: `uv run pytest tests/test_config_models.py -v` — all contract tests pass
- [x] **Logic tests** (`tests/test_config_models.py`): positive — valid `Viewport`/`Action`/`Component`/`Page`/`Suite`
      construct and expose fields; negative (parametrized `pytest.raises(ValidationError)`) — `kind="explode"`,
      `threshold=5` / `threshold=0` / `threshold=1`, `tolerance=150` / `tolerance=0`, `width=0`,
      `viewports=[]`, duplicate component names in one `Page`, `wait_until="eager"`,
      `url=None` + setup not starting with `open`, `url` set + setup starting with `open`;
      edge — same component name on TWO different pages is ACCEPTED; components come out name-sorted
      regardless of input order
- [x] **Debugging**: `uv run pytest tests/test_config_models.py -v` — fix implementation code until all
      tests pass (do NOT fix test code)
- [x] **Contract re-verification**: verify facade `__all__`, signatures, and property types against
      `peeksy/config/CODEMANIFEST`
- [x] **Lint**: `uv run ruff check peeksy/config tests/test_config_models.py` + `uv run ruff format --check peeksy/config tests/test_config_models.py` — fix formatting, apply decomposition if necessary

### Task 3: `peeksy/config` — `load_config` site-folder loader (TDD)

Covers contract routine `load_config` at `location: loader.py`, and completes the cell facade.
Design Code Stack Trace (verbatim — implement exactly this):

1. **Input**: `path` — a suite file path (any explicitly passed `*.yml` — `peeksy.yml` in the project root by convention, default of `--config`), or a site folder. → checkpoint: path exists (IO error otherwise).
2. Resolve site dir: an explicitly passed `*.yml` file IS the suite file → use its parent as the site dir; a folder → look up `suite.yml` inside it. → checkpoint: the suite file exists under the resolved dir.
3. Read + validate the resolved suite file into suite meta (`name`, `baseline_path`, `results_path`, `report_path`, `threshold`, `tolerance`) via Pydantic; normalize relative paths to absolute **against the site folder** (CWD-independence). → checkpoint: `ValidationError` on bad YAML/types/out-of-range threshold/tolerance, surfaced human-readable.
4. Enumerate `pages/*/` subfolders. For each: read `page.yml` (`url`, `setup`); discover components as the other `*.yml` files in that folder. → checkpoint: `page.yml` required; non-`*.yml` files ignored.
5. Parse each component file: short-form `setup` actions → `Action(kind, target, value)` per per-kind rules; derive `Component.name` from filename, `Page.name` from folder name. → checkpoint: `ValueError` on malformed action (e.g. `fill` without list); `ValidationError` on out-of-range overrides, non-positive viewport dimensions, or empty `viewports`.
6. Per-page uniqueness: `model_validator` rejects duplicate `Component.name` within a page. → checkpoint: dup → `ValidationError`.
7. **Output**: `Suite` with `pages`. Consumer: `runner` / `cli`.

Short-form action parsing lives HERE (config), not in capture — `capture` only executes `Action`
by `kind`. Parse rules: a single string is the target for click/hover/scroll_to or the value for
press/scroll_by/open; a list is `[target, value]` for fill/select (and optionally press);
wait takes a selector (appear), `{selector: ..., hidden: true}` (disappear), a millisecond number (pause),
or nothing (default stabilization); open takes a URL value. `- reload: {}` parses to `Action("reload", None, None)`.

**Usages relevant to this task:**
- `pydantic_config` (inline, `peeksy/config/CODEMANIFEST`): site-folder discovery rules, short-form action parsing, path normalization against the site folder.
- `peeksy/config/.usages/config.md`: consumer view of the loader — the short-form YAML examples there are valid parse inputs.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests** (`tests/test_config_loader.py`): `load_config` importable from `peeksy.config`;
      signature `load_config(path: str) -> Suite` via `inspect` (expected to fail now)
- [x] **Code**: create `peeksy/config/loader.py` — implement `load_config` per the 7-step trace above;
      internal helpers (`_resolve_site_dir`, `_parse_action`, page/component walking) stay private in
      the same file; use `yaml.safe_load`
- [x] **Code**: normalize relative `baseline_path`/`results_path`/`report_path` against the resolved
      site folder; absolute paths pass through unchanged
- [x] **Code**: add `load_config` to the facade `__all__` in `peeksy/config/__init__.py`
- [x] **Interface verification**: `uv run pytest tests/test_config_loader.py -v` — contract tests pass
- [x] **Logic tests** (`tests/test_config_loader.py`):
      `test_load_config_builds_suite_from_site_folder` (design scenario: site folder with
      `suite.yml` threshold=0.1 tolerance=0.5, `pages/home/page.yml` with `- click: "#cookie"`,
      `pages/home/header.yml` with viewports `[{1280,720}]`; assert `pages[0].name == "home"`,
      `components[0].name == "header"`, `components[0].viewports[0].width == 1280`, `suite.tolerance == 0.5`);
      `test_load_config_resolves_relative_paths_against_site_folder` (`monkeypatch.chdir` elsewhere —
      paths come out absolute and site-anchored, not CWD-anchored);
      `test_load_config_rejects_invalid_page_and_action_shapes` (parametrized, 8 cases from the design:
      `wait_until: eager`; `url: null` without leading `open`; set `url` WITH leading `open`;
      `- fill: "#search"` bare string; `threshold: 5`; `tolerance: 150`; `viewports: []`;
      `viewports: [{width: 0, height: 720}]` — each raises `ValidationError` mentioning the offending field);
      `test_load_config_rejects_duplicate_component_name_within_page`;
      edge — explicit `*.yml` suite file accepted under any filename (parent = site dir);
      folder arg looks up `suite.yml`; empty `pages/` → `Suite(pages=[])`; missing path → `FileNotFoundError`
- [x] **Debugging**: `uv run pytest tests/test_config_loader.py tests/test_config_models.py -v` — fix
      implementation until all pass (do NOT fix test code)
- [x] **Contract re-verification**: `load_config` signature, return type, and facade exposure match
      `peeksy/config/CODEMANIFEST`
- [x] **Lint**: `uv run ruff check peeksy/config tests/test_config_loader.py` + `uv run ruff format --check peeksy/config tests/test_config_loader.py`

### Task 4: `peeksy/compare` — `ComparisonResult` + `compare` (TDD)

Covers the whole compare cell: entity `ComparisonResult` (`result.py`) and routine `compare`
(`compare.py`); creates facade `peeksy/compare/__init__.py`. Design algorithm (verbatim):

```
1. baseline, current = Image.open(...).convert("RGBA") x2
2. IF baseline.size != current.size: return ComparisonResult(False, 100.0, None)
3. diff = Image.new("RGBA", baseline.size)
4. mismatched = pixelmatch(baseline, current, diff, threshold, includeAA=True)
5. pct = mismatched / (w*h) * 100; passed = pct <= tolerance
6. IF not passed: diff.save(diff_path); return ComparisonResult(False, pct, diff_path)
   ELSE: return ComparisonResult(True, pct, None)
```

Diff file naming: derive from the BASELINE filename stem + `.diff.png` (baseline
`{name}_{WxH}.png` → diff `{name}_{WxH}.diff.png`) so the runner's `run_policy` path convention
holds; create `diff_dir` (parents) before saving. Contract nuance overriding the cook's example
snippet: the diff is saved only when NOT passed (`diff_path=None` otherwise) — the contract, not
the cook, is authoritative.

**Usages relevant to this task:**
- `image_diff` (`.goga/usages/cooks/image-diff.md`): read fully — RGBA conversion, size guard,
  `includeAA=True`, the two-threshold model. Import: `from pixelmatch.contrib.PIL import pixelmatch`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (`tests/test_compare.py`): `compare` and `ComparisonResult` importable from
      `peeksy.compare`; `compare` signature
      `(baseline: str, current: str, diff_dir: str, threshold: float, tolerance: float) -> ComparisonResult`;
      `ComparisonResult` exposes `passed: bool`, `mismatch_percent: float`, `diff_path: str | None`
      (expected to fail now)
- [ ] **Code**: create `peeksy/compare/result.py` — `ComparisonResult` record (dataclass or Pydantic
      model — either satisfies the contract; keep it a plain immutable record)
- [ ] **Code**: create `peeksy/compare/compare.py` — implement the 6-step algorithm; create
      `peeksy/compare/__init__.py` facade with `__all__ = ["ComparisonResult", "compare"]`
- [ ] **Interface verification**: `uv run pytest tests/test_compare.py -v` — contract tests pass
- [ ] **Logic tests** (`tests/test_compare.py`), synthetic PNGs via PIL — no browser:
      `test_compare_passes_on_identical_images` (byte-identical PNGs → `passed is True`,
      `mismatch_percent == 0.0`, `diff_path is None`, no diff file written);
      `test_compare_tolerance_boundary_semantics` (100x100 baseline, current with exactly 100 pixels
      altered = 1.0%; `tolerance=1.0` → passed (non-strict `<=`), no diff; `tolerance=0.99` → failed,
      diff file exists — pins the `<=` semantics);
      `test_compare_size_change_is_definite_failure` (1280x720 vs 1280x800 → `passed is False`,
      `mismatch_percent == 100.0`, `diff_path is None`, no exception);
      edge — small real diff (e.g. 2px shift) → failed, diff PNG written into `diff_dir`, diff file
      loadable by PIL
- [ ] **Debugging**: `uv run pytest tests/test_compare.py -v` — fix implementation until all pass
      (do NOT fix test code)
- [ ] **Contract re-verification**: facade, signatures, and the passed/diff-path semantics match
      `peeksy/compare/CODEMANIFEST`
- [ ] **Lint**: `uv run ruff check peeksy/compare tests/test_compare.py` + `uv run ruff format --check peeksy/compare tests/test_compare.py`

### Task 5: `peeksy/reporting` — `Outcome` + `write_results` (TDD)

Covers entity `Outcome` (`outcome.py`) and routine `write_results` (`writer.py`); creates the facade
`peeksy/reporting/__init__.py` exposing `Outcome` and `write_results`. Design Code Stack Trace (verbatim):

1. **Input**: `list[Outcome]`, `results_dir`.
2. Create `results_dir` (mkdir, parents) if absent. → checkpoint: writing succeeds on a fresh site checkout.
3. For each `Outcome`: compute `testCaseId`/`historyId` = `peeksy::{suite}::{page}::{name}[{viewport}]`; display name `{suite} / {page} / {name} [{viewport}]`; Allure suite label = `suite`. → checkpoint: stable across runs; never collapses across sites, pages, or viewports (one history row per (component, viewport)).
4. For non-None among `baseline_path`/`current_path`/`diff_path`: copy PNG into `results_dir` as `<uuid>-attachment`; skip None. → checkpoint: BROKEN outcomes omit the missing image cleanly.
5. Build `TestResult` (allure-commons): status mapped PASSED→`Status.PASSED`, FAILED→`Status.FAILED`, BROKEN→`Status.BROKEN`; attach copied PNGs.
6. `statusDetails`: mismatch `%` when FAILED; `error` message when BROKEN.
7. Write `<uuid>-result.json`. → checkpoint: one JSON per Outcome.
8. **Output**: populated `results_dir`. No return value. Clearing prior runs is the runner's responsibility.

`mismatch_percent` is `None` for BROKEN — never rendered, never a fake `0.0`.

**Usages relevant to this task:**
- `allure` (`.goga/usages/cooks/allure.md`): read fully — Stage 1 model usage
  (`allure_commons.model2.TestResult/Attachment/Status/StatusDetails/Label`), `copy_attachment`
  convention (`<new-uuid>-attachment`), stable `historyId`/`testCaseId`, JSON serialization approach.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (`tests/test_reporting_writer.py`): `Outcome` and `write_results` importable
      from `peeksy.reporting`; `write_results(outcomes: list[Outcome], results_dir: str)` returns None;
      `Outcome` exposes all ten properties with declared types (expected to fail now)
- [ ] **Code**: create `peeksy/reporting/outcome.py` — `Outcome` record (dataclass or Pydantic model,
      all ten fields per the contract signature)
- [ ] **Code**: create `peeksy/reporting/writer.py` — implement the 8-step trace; copy attachments as
      `<uuid>-attachment`; create `peeksy/reporting/__init__.py` facade with
      `__all__ = ["Outcome", "write_results"]`
- [ ] **Interface verification**: `uv run pytest tests/test_reporting_writer.py -v` — contract tests pass
- [ ] **Logic tests** (`tests/test_reporting_writer.py`, tmp_path + tiny PIL-generated PNGs):
      positive — PASSED outcome with baseline+current → one `*-result.json`, name
      `{suite} / {page} / {name} [{viewport}]`, `historyId`/`testCaseId` ==
      `peeksy::{suite}::{page}::{name}[{viewport}]`, suite label == outcome.suite, exactly two
      attachments copied; FAILED with diff → three attachments, `status == "failed"`,
      `statusDetails` mentions the mismatch percent; negative — BROKEN with `current_path=None`
      → current attachment omitted, `status == "broken"`, `statusDetails` carries the error,
      `mismatch_percent` (None) NOT rendered; edge — fresh (absent) `results_dir` created;
      two viewports of the same component → two JSONs with DISTINCT `historyId`s
      (`…[1280x720]` vs `…[375x667]`)
- [ ] **Debugging**: `uv run pytest tests/test_reporting_writer.py -v` — fix implementation until all
      pass (do NOT fix test code)
- [ ] **Contract re-verification**: facade, signatures, and Allure conventions match
      `peeksy/reporting/CODEMANIFEST`
- [ ] **Lint**: `uv run ruff check peeksy/reporting tests/test_reporting_writer.py` + `uv run ruff format --check peeksy/reporting tests/test_reporting_writer.py`

### Task 6: `peeksy/reporting` — `build_report` (TDD)

Covers routine `build_report` (`report.py`); completes the reporting facade. Design Code Stack Trace (verbatim):

1. **Input**: results dir, report dir.
2. `shutil.which("allure")` → if None: raise a human-readable error with install instructions. → checkpoint: never let `subprocess` fail with `FileNotFoundError`.
3. `subprocess.run(["allure","generate",results_dir,"--clean","-o",report_dir], check=True, capture_output=True)`. → checkpoint: non-zero exit raises `CalledProcessError` (with captured stderr surfaced); positional results dir first — canonical `allure generate` argument order.
4. **Output**: HTML report in `report_dir`.

Raise `RuntimeError` with the install hint (brew/sdkman, requires JDK) — the CLI (Task 9) catches
exactly this. NOTE: the argv order above (results dir positional FIRST) is authoritative — it
overrides the example snippet in `.goga/usages/cooks/allure.md` which shows the results dir last.

**Usages relevant to this task:**
- `allure` (`.goga/usages/cooks/allure.md`): Stage 2 — external CLI invocation, `--clean` semantics.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (`tests/test_reporting_report.py`): `build_report` importable from
      `peeksy.reporting`; signature `build_report(results_dir: str, report_dir: str)` (expected to fail now)
- [ ] **Code**: create `peeksy/reporting/report.py` — implement the trace; add `build_report` to the
      facade `__all__`
- [ ] **Interface verification**: `uv run pytest tests/test_reporting_report.py -v` — contract tests pass
- [ ] **Logic tests** (`tests/test_reporting_report.py`, everything stubbed — no JDK needed):
      `test_build_report_missing_allure_raises_human_readable` (`monkeypatch.setattr(shutil, "which", lambda _: None)`
      → `pytest.raises(RuntimeError)` with install hint; assert `subprocess.run` NOT called);
      `test_build_report_invokes_allure_with_canonical_args` (which → `"/usr/bin/allure"`;
      recording spy for `subprocess.run` returning a completed-process stub; assert exactly one call,
      `args == ["allure", "generate", "/tmp/results", "--clean", "-o", "/tmp/report"]`, `check is True`,
      `capture_output is True`);
      edge — allure exits non-zero → spy raises/returns non-zero → `CalledProcessError` propagates
- [ ] **Debugging**: `uv run pytest tests/test_reporting_report.py -v` — fix implementation until all
      pass (do NOT fix test code)
- [ ] **Contract re-verification**: facade and behavior match `peeksy/reporting/CODEMANIFEST`
- [ ] **Lint**: `uv run ruff check peeksy/reporting tests/test_reporting_report.py` + `uv run ruff format --check peeksy/reporting tests/test_reporting_report.py`

### Task 7: `peeksy/capture` — `CaptureSession` with two-level setup (TDD)

Covers entity `CaptureSession` (`session.py`) — methods `open`, `open_page`, `capture_component`,
`close`; creates facade `peeksy/capture/__init__.py`. Imports `Component`, `Viewport`, `Page`,
`Action` from `peeksy/config` (already implemented). Design Code Stack Traces (verbatim):

**`open()`**: `sync_playwright().start()`; `p.chromium.launch(headless=True)`; `browser.new_context(device_scale_factor=1)`; `context.new_page()`. Store on self.

**`open_page(page, viewport)`**:
1. `page.set_viewport_size({"width":vp.width,"height":vp.height})`.
2. If `page.url` is not None: `page.goto(page.url, wait_until=page.wait_until)` — strategy from the config (`networkidle` by default; `domcontentloaded`/`load` for live pages). When `url` is None (deep-link flow — validated to start with an `open` action), navigation is performed by that first setup action.
3. Inject CSS disabling animations/transitions + `caret-color: transparent`; `page.evaluate("document.fonts.ready")`.
4. For each `Action` in `page.setup`: execute via Playwright per `kind` (see `run_actions`).

**`capture_component(component, out_path) -> str`**:
1. For each `Action` in `component.setup`: execute per `kind`.
2. Re-apply the determinism CSS (animation-disable + `caret-color`) and `document.fonts.ready` — an `open`/`reload` inside the setup navigates away and drops the `<style>` injected by `open_page` (and the deep-link flow injects it on a blank page). → checkpoint: determinism holds even for `- reload: {}` components and deep-link pages.
3. Locate `component.selector` — plain CSS, piercing (`a >> b`), or iframe (`frame_locator(...).locator(...)`) — `.first`; `wait_for(state="visible")`. → checkpoint: page settled before masking — masked zones exist in the DOM.
4. For each `mask_selectors`: lay an opaque gray `::after` overlay over `locate(page, sel)` — the SAME helper as for the component selector — by injecting a `.peeksy-mask` class (`add_style_tag` + `evaluate`). → checkpoint: pixel-identical masks regardless of underlying content; never `display:none` (preserve layout box); masks symmetric with the component selector.
5. `screenshot(type="png", path=out_path)`.
6. Remove the `peeksy-mask` class from every masked element (same locate helper). → checkpoint: the next capture on this page starts unmasked — no mask leakage across components.
7. **Output**: `out_path` (== written PNG path).

**`close()`**: `context.close()`; `browser.close()`; stop playwright. → checkpoint: idempotent teardown.

Determinism constants (from the design):
- `ANIM_DISABLE_CSS`: `*, *::before, *::after {animation: none !important; transition: none !important; caret-color: transparent !important;}`
- Mask CSS: `.peeksy-mask { position: relative; } .peeksy-mask::after { content: ""; position: absolute; inset: 0; background: #808080; z-index: 99999; }`

Internal helpers (private, same file): `run_actions(page, actions, wait_strategy)` dispatching per
`kind` (table in `playwright.md` — click/hover/scroll_to/scroll_by/fill/press/select/wait/open/reload),
`locate(page, selector)` supporting plain CSS / `a >> b` piercing / iframe selectors via
`frame_locator` — used for BOTH the component selector and every mask selector, and
`run_wait(page, action)` per the wait rules.

**Usages relevant to this task:**
- `playwright` (`.goga/usages/cooks/playwright.md`): read fully BEFORE implementing — lifecycle
  (one browser/context, DPR=1), capture routine, `run_actions` dispatch table, wait rules, masking
  overlay pattern (incl. the wait_for-BEFORE-mask order and unmask-after-shot), viewport handling,
  failure modes. Errors: `playwright.sync_api.Error`/`TimeoutError` propagate to the runner (→ BROKEN there).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (`tests/test_capture_session.py`): `CaptureSession` importable from
      `peeksy.capture`; methods `open()`, `open_page(page: Page, viewport: Viewport)`,
      `capture_component(component: Component, out_path: str) -> str`, `close()` exist with matching
      signatures via `inspect` (expected to fail now)
- [ ] **Code**: create `peeksy/capture/session.py` — `CaptureSession` + private helpers
      (`run_actions`, `locate`, `run_wait`) per the traces and `playwright.md`; create facade
      `peeksy/capture/__init__.py` with `__all__ = ["CaptureSession"]`
- [ ] **Code**: create `tests/conftest.py` with a `fixture_site` factory: writes a local HTML page
      (served via `file://` — no HTTP server needed) containing `#header` with a
      `<span class="timestamp">` filled by JS with `Date.now()` on load, and a `#footer` (no dynamic
      content); the factory returns the HTML path so tests can copy/rewrite it
- [ ] **Interface verification**: `uv run pytest tests/test_capture_session.py -v` — contract tests pass
- [ ] **Logic tests** (`tests/test_capture_session.py`, REAL Chromium against the file:// fixture):
      positive — `open()` + `open_page(Page(url=<fixture>, wait_until="networkidle"), Viewport(1280, 720))`
      then `capture_component(Component(selector="#header", ...), out_path)` writes a loadable PNG and
      returns `out_path`; `test_open_action_navigates_mid_setup` (deep-link `Page(url=None,
      setup=[open <fixture>, click "#x"])` — spy/wrap `page.goto` (or the session's navigation) and
      assert it was called with the deep URL); `test_capture_is_idempotent_pixelmatch_clean` (capture
      the same component twice back-to-back → `peeksy.compare.compare` returns
      `passed is True`, `mismatch_percent == 0.0`); edge — `test_masked_dynamic_region_stable_and_no_mask_leakage`
      at session level: capture `#header` with `mask_selectors=[".timestamp"]`, then immediately
      capture `#footer`; re-load the page (new timestamp) and repeat; both header compares pass and a
      PIL scan of the footer PNG finds NO pixel of exactly `#808080` (no mask leakage); a component
      whose setup is `- reload: {}` still captures pixelmatch-clean against a non-reload capture
      (determinism re-inject); `close()` tears down and is safe to call once more (idempotent)
- [ ] **Debugging**: `uv run pytest tests/test_capture_session.py -v` — fix implementation until all
      pass (do NOT fix test code)
- [ ] **Contract re-verification**: facade, method signatures, and the two-level setup semantics match
      `peeksy/capture/CODEMANIFEST`; no Playwright import leaks outside the capture cell
- [ ] **Lint**: `uv run ruff check peeksy/capture tests/test_capture_session.py tests/conftest.py` + `uv run ruff format --check peeksy/capture tests/test_capture_session.py tests/conftest.py`

### Task 8: `peeksy/runner` — `run_generate` / `run_test` / `run_report` (TDD)

Covers the three runner routines (all `location: runner.py` — one task per the same-location rule);
creates facade `peeksy/runner/__init__.py`. Imports (already implemented): config, capture, compare,
reporting types. Design Code Stack Traces (verbatim):

**`run_generate(suite, pages, components)`**:
1. **Input**: `Suite`, optional name filters.
2. Filter `suite.pages` by `pages`; within each page filter `components` by name (None ⇒ all). If the filtered result is empty, return immediately WITHOUT opening the CaptureSession (no browser launch for a no-op run).
3. `CaptureSession.open()`; capture loop in try/finally (fail-fast: the first capture error closes the session and propagates; re-run with `--page`/`--component` to resume).
4. For each page: ordered dedupe of viewports across its filtered components (first-seen order over the name-sorted components — deterministic, no set iteration since `Viewport` is unhashable); for each viewport: `open_page(page, viewport)`; for each component at that viewport (name-sorted order — deterministic regardless of filesystem ordering): `capture_component` into `{baseline_path}/{page}/{name}_{WxH}.png`.
5. `CaptureSession.close()` in the finally block.
6. **Output**: baseline PNGs written. No return.

**`run_test(suite, pages, components) -> int`**:
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

**`run_report(suite)`**: `build_report(suite.results_path, suite.report_path)`. Propagates the
missing-allure error to `cli`.

Viewport label format: `f"{width}x{height}"` (e.g. "1280x720") — used in paths, `Outcome.viewport`,
and testCaseId. `Outcome.suite` = `suite.name`. Playwright types must NOT leak into the runner —
it depends on `CaptureSession` only.

**Usages relevant to this task:**
- `run_policy` (inline, `peeksy/runner/CODEMANIFEST`): read fully — path conventions, capture grouping,
  BROKEN policy, clearing rules, fail-fast vs continue semantics, effective threshold/tolerance.
- `peeksy/runner/.usages/runner.md`: consumer view of the three routines.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (`tests/test_runner.py`): `run_generate`, `run_test`, `run_report` importable
      from `peeksy.runner`; signatures match
      (`run_generate(suite: Suite, pages: list[str] | None, components: list[str] | None)` etc.;
      `run_test` returns `int`) (expected to fail now)
- [ ] **Code**: create `peeksy/runner/runner.py` — implement the three routines exactly per the traces;
      private helpers allowed in the same file (filtering, viewport dedupe, path builders
      `{baseline_path}/{page}/{name}_{WxH}.png`, `{results_path}/{page}/{name}_{WxH}.current.png`,
      `{results_path}/{page}/{name}_{WxH}.diff.png`, results clearing by exact patterns)
- [ ] **Code**: create facade `peeksy/runner/__init__.py` with `__all__ = ["run_generate", "run_test", "run_report"]`
- [ ] **Interface verification**: `uv run pytest tests/test_runner.py -v` — contract tests pass
- [ ] **Logic tests** (`tests/test_runner.py` — use a FakeCaptureSession monkeypatched over
      `peeksy.runner.runner.CaptureSession` whose `capture_component` writes a small PIL-generated PNG
      to `out_path`, `open_page` raises on demand; plus real `Suite` objects built directly — no browser
      needed at this level):
      `test_generate_and_test_honor_page_component_filters` (2 pages × 2 components; filter
      `pages=["home"], components=["header"]` → exactly ONE baseline PNG at
      `home/header_{WxH}.png`, `about/**` and `sidebar_*` absent; `run_test` with the same filter → 0,
      exactly one `*-result.json`);
      `test_run_test_page_setup_failure_marks_all_components_broken` (fake `open_page` raises for page
      "home", succeeds for "about" → home result `"broken"` with error containing "page setup failed"
      and no current attachment; about result `"passed"`; exit 1; run continued);
      `test_run_test_missing_baseline_is_broken` (no baseline generated → BROKEN, error contains
      "baseline not found", `mismatch_percent is None`, exit 1);
      `test_run_test_empty_selection_is_noop_preserving_results` (produce results first, record JSON
      count, fake session's `open` set to raise AssertionError if called; `run_test(suite, pages=["nonexistent"])`
      → 0, open NOT called, JSON count unchanged);
      `test_results_dir_cleared_between_test_runs` (run twice; after run 2 the count of `*-result.json`
      equals current outcomes, no run-1 leftovers);
      edge — current-run `.current.png` files SURVIVE the clear (patterns `*-result.json`/`*-attachment`
      only); stale `{results_path}/{page}/` subdir of a REMOVED component is wiped by step 2.5;
      component `tolerance`/`threshold` override wins over suite default (fake images engineered to
      fail at suite default but pass at the override, or assert the values forwarded to a `compare` spy);
      ordered viewport dedupe preserves first-seen order over name-sorted components (spy on
      `open_page` call order); exit code 0 when all PASSED;
      `run_report` delegates (spy on `build_report` — called with `suite.results_path`, `suite.report_path`)
- [ ] **Debugging**: `uv run pytest tests/test_runner.py -v` — fix implementation until all pass
      (do NOT fix test code)
- [ ] **Contract re-verification**: facade, signatures, and orchestration semantics match
      `peeksy/runner/CODEMANIFEST`; no Playwright import in `peeksy/runner/`
- [ ] **Lint**: `uv run ruff check peeksy/runner tests/test_runner.py` + `uv run ruff format --check peeksy/runner tests/test_runner.py`

### Task 9: `peeksy/cli` — Typer facade `generate`/`test`/`report`/`main` (TDD)

Covers the four cli routines (all `location: app.py`); creates facade `peeksy/cli/__init__.py`.
Design Code Stack Trace (verbatim):

1. `load_config(config_path)` → `Suite`. Configuration errors are caught by a single app-level Typer exception handler: `pydantic.ValidationError` (bad types/duplicates/ranges), `yaml.YAMLError` (syntactically broken YAML never reaches Pydantic), `FileNotFoundError`/`NotADirectoryError` (missing `--config` path) — printed as a human-readable message (no Python traceback), then `typer.Exit(code=1)` — applies to all three commands.
2. Delegate to runner (`run_generate`/`run_test`/`run_report`) with `page`/`component` filters.
3. `test`: print one-line summary from exit code; `raise typer.Exit(code=exit_code)`.
4. `report`: catch missing-allure error → print install message + `typer.Exit(code=1)`.
5. `main`: run the Typer app.

Option declarations (binding): `--config`/`-c` as `Annotated[str, typer.Option("--config", "-c")]`
with default `"./peeksy.yml"`; `--page` and `--component` as repeatable
`Annotated[list[str] | None, typer.Option("--page")]` / `("--component")]`, combined as AND.
NEVER `sys.exit` — always `raise typer.Exit(code=...)`. Summary line for `test`: "all components
passed" when 0, otherwise "regression or infrastructure failure detected — see the Allure report".
Typer has no native global exception hook — implement the ONE shared handler as a single helper
(e.g. a decorator or wrapper function) applied to all three command bodies; do not duplicate the
try/except in each command. The missing-allure error from `report` is the `RuntimeError` raised by
`build_report` (Task 6).

**Usages relevant to this task:**
- `typer` (inline, `peeksy/cli/CODEMANIFEST`): command/option declarations, exit-code policy, app-level handler contract.
- `peeksy/cli/.usages/cli.md`: shell-level view — the exact flags and their semantics.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (`tests/test_cli.py`): `generate`, `test`, `report`, `main` importable from
      `peeksy.cli`; a module-level Typer `app` exists; `main()` callable (expected to fail now)
- [ ] **Code**: create `peeksy/cli/app.py` — Typer app + three commands + `main()` per the trace;
      shared config-error handler; create facade `peeksy/cli/__init__.py` with
      `__all__ = ["app", "generate", "test", "report", "main"]`
- [ ] **Interface verification**: `uv run pytest tests/test_cli.py -v` + `uv run python -m peeksy.cli.app --help`-style smoke via CliRunner (expected: three commands listed)
- [ ] **Logic tests** (`tests/test_cli.py`, `typer.testing.CliRunner`; stub `run_*` via monkeypatch on
      `peeksy.cli.app.run_generate`/`run_test`/`run_report` and `load_config` where a Suite is needed —
      no browser): `--page`/`--component` repeatable options forwarded to the runner (spy);
      `--config` default is `./peeksy.yml` (spy on `load_config` with no `-c` passed);
      `test` exit code propagates (stub returns 1 → `result.exit_code == 1`, summary line printed;
      stub returns 0 → exit 0, "all components passed");
      app-level handler (parametrized): invalid config file → `ValidationError`, broken YAML → `yaml.YAMLError`,
      missing path → `FileNotFoundError` — each surfaces a human-readable message, `exit_code == 1`,
      NO Python traceback in output;
      `test_cli_report_prints_install_hint_when_allure_absent` (`run_report` stub raises the
      RuntimeError from Task 6 → exit 1, stdout mentions "allure", no traceback);
      `generate` delegates and exits 0
- [ ] **Debugging**: `uv run pytest tests/test_cli.py -v` — fix implementation until all pass
      (do NOT fix test code)
- [ ] **Contract re-verification**: facade, command surface, flags, and exit-code policy match
      `peeksy/cli/CODEMANIFEST`; console script works: `uv run peeksy --help` lists generate/test/report
- [ ] **Lint**: `uv run ruff check peeksy/cli tests/test_cli.py` + `uv run ruff format --check peeksy/cli tests/test_cli.py`

### Task 10: Integration tests — end-to-end generate → test → report (real browser)

Cross-cell verification of the acceptance criteria that need a REAL Chromium: the full pipeline
(config → capture → compare → reporting → cli) against local `file://` fixture pages whose state
mutates on disk between generate and test. These tests do NOT replace the per-cell contract/logic
tests from Tasks 2–9 — they verify the interactions.
The fixture pages come from `tests/conftest.py` (`fixture_site` factory, Task 7): `#header` with a
`.timestamp` span randomized by JS on load, `#footer` stable; tests copy the HTML into `tmp_path`
and rewrite it to introduce the mutation (the mutation lives ON DISK so it survives `open_page`
reloading the URL between generate and test).

**Usages relevant to this task:**
- `playwright` (`.goga/usages/cooks/playwright.md`): failure modes — selector-missing → TimeoutError → BROKEN upstream.
- `image_diff` (`.goga/usages/cooks/image-diff.md`): determinism of the verdict.
- `allure` (`.goga/usages/cooks/allure.md`): result JSON shape asserted in tests.

- [ ] Create `tests/test_integration.py` reusing the `conftest.py` fixture factory
- [ ] `test_run_generate_then_test_passes` (design scenario, verbatim): local fixture page; `Suite`
      with one component at 1280x720; `run_generate(suite, None, None)` then `run_test(suite, None, None)`
      → `exit_code == 0`; one `*-result.json` in `results_path`; baseline exists at
      `{baseline_path}/home/header_1280x720.png`
- [ ] `test_cli_test_exits_nonzero_on_regression` (design scenario, verbatim): generate against the
      original HTML; rewrite the HTML on disk adding `style="transform: translateY(2px)"` to `#header`;
      `CliRunner().invoke(app, ["test", "--config", site])` → `result.exit_code == 1`; summary printed;
      `*-result.json` has `"status": "failed"` with mismatch in `statusDetails`; diff attachment file
      exists in `results_path`
- [ ] `test_regression_in_single_viewport_fails_only_that_result` (design scenario, verbatim):
      component with viewports 1280x720 + 375x667; baseline both; rewrite HTML shifting `#header` ONLY
      via `@media (max-width: 500px)`; `run_test(suite, None, None)` → exit 1; exactly 2
      `*-result.json`, one passed one failed; baseline filenames `_1280x720.png` / `_375x667.png`
      (no collision); the two results carry distinct `historyId`s (`…::header[1280x720]` vs
      `…::header[375x667]`)
- [ ] `test_masked_dynamic_region_stable_and_no_mask_leakage` (design scenario, verbatim): full
      generate→test flow with `header.mask_selectors=[".timestamp"]` (timestamp re-randomized on
      reload); both outcomes `"passed"`; PIL scan of the footer PNG finds NO pixel of the exact mask
      gray `#808080`
- [ ] Edge: `peeksy report` end-to-end with allure stubbed (which → real path, `subprocess.run` spy)
      via CliRunner — exits 0 and the spy saw the canonical argv; `uv run peeksy --help` smoke
- [ ] Run validation: `uv run pytest tests/test_integration.py -v` — all pass; fix product code
      (not tests) on failure
- [ ] Full-suite gate: `uv run pytest` — every test in the project green

---

## Validation Commands

- `uv run pytest`: Run all tests (full green gate)
- `uv run pytest tests/<file>.py -v`: Run one task's test file
- `uv run ruff check peeksy tests` + `uv run ruff format --check peeksy tests`: Lint + formatting
- `uv run python -c "from peeksy.config import Viewport, Action, Component, Page, Suite, load_config; from peeksy.compare import compare, ComparisonResult; from peeksy.reporting import Outcome, write_results, build_report; from peeksy.capture import CaptureSession; from peeksy.runner import run_generate, run_test, run_report; from peeksy.cli import app, generate, test, report, main"`: Verify every facade entity is importable
- `uv run peeksy --help`: Console script smoke — generate/test/report listed

---

## Completion Criteria

- [ ] Every contract entity is implemented in the correct `location`
- [ ] Every contract entity is accessible from the facade (`__all__`)
- [ ] Properties and methods match the declared API
- [ ] Descriptions are reflected in behavior
- [ ] Contract dependencies are met (imports resolve leaves → root)
- [ ] Re-exports are accessible from the facade (none declared — n/a)
- [ ] Every coding task followed the TDD workflow (contract tests → code → verification → logic tests → debugging → re-verification → lint)
- [ ] Contract tests and logic tests cover facade, API, and behavior within each coding task
- [ ] Integration tests exist for the cross-cell scenarios (Task 10)
- [ ] No package boundary was expanded (no new cells; Playwright stays inside `peeksy/capture`)
- [ ] `CODEMANIFEST` files were not modified (contract is read-only)
- [ ] All validation commands pass
- [ ] Every Usages entry is exercised in at least one task (`pydantic_config` → T2/T3, `image_diff` → T4/T10, `allure` → T5/T6/T10, `playwright` → T7/T10, `run_policy` → T8, `typer` → T9)
