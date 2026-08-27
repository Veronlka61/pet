# Architecture Plan — peeksy CLI

- **Topic:** `peeksy-cli`
- **Source task:** `docs/tasks/peeksy-cli.md`
- **Language:** Python (cell = package with `CODEMANIFEST` + `__init__.py`)
- **Base usages/annotations:** none (`.goga/config.yml` absent → no project-wide mandatory practices)
- **Created:** 13/07/26

This plan defines the cells architecture for the `peeksy` visual-regression CLI:
which cells, their `CODEMANIFEST` files, their `.usages/` consumer docs, the import
graph, and the implementation order. It contains **only** CODEMANIFEST and `.usages/`
artifacts — no implementation code.

## Configuration layout (variant D — site / page / component)

A site is a **folder**; a page is a **folder**; a component is a **file**. Each file is
small and human-editable, and per-page/per-component setup actions live next to what
they prepare:

```
sites/<site>/suite.yml                       # Site meta: name, baseline/results/report paths, threshold/tolerance defaults
sites/<site>/pages/<page>/page.yml           # Page meta: url + page-level `setup` actions
sites/<site>/pages/<page>/<component>.yml    # Component: selector, viewports, masks, threshold/tolerance override, component-level `setup`
```

Conventions:

- `Component.name` is derived from its filename (without `.yml`); `Page.name` from its
  folder name. Editing a file/folder name renames the entity — no duplicate `name` field.
- A page's components are **all** `*.yml` files next to its `page.yml` (auto-discovery).
- `Component.name` must be unique **within a page** (not across the whole site): the
  baseline path and Allure `testCaseId` are namespaced by page, so `home/header` and
  `about/header` never collide.

## Design decisions (approved)

1. **6 cells** — `config`, `compare`, `reporting`, `capture`, `runner`, `cli`. `runner`
   is a separate cell (orchestration, testable without Typer); `cli` is a thin Typer facade.
2. **Three-level config (variant D)** — site folder → page folder → component file.
   `Suite` holds `pages: list[Page]`; each `Page` holds `url`, page-level `setup`, and
   `components: list[Component]`. `url` lives on the page, not on the component.
3. **Two-level setup actions** — `Page.setup` runs once per `(page, viewport)` after
   navigation (e.g. close cookie banner, log in); `Component.setup` runs before that
   component's shot (e.g. hover, click a tab). Both are `list[Action]`. Page setup is
   never duplicated across the components of one page.
4. **`CaptureSession`** is a stateful Entity owning the Playwright lifecycle (one browser +
   one context, DPR=1, reused across the run). Playwright does not leak into `runner`.
   Capture is split into `open_page` (navigate + page setup, once per page+viewport) and
   `capture_component` (component setup + mask + screenshot).
5. **Two verdict types** — `ComparisonResult` (compare output: image-focused) and `Outcome`
   (reporting input: adds page/component identity + `BROKEN` status). The runner maps one to the other.
6. **Configurable deviation %** lives in YAML only — `Suite.tolerance` (default) and
   `Component.tolerance` (per-component override, `None` ⇒ inherit). No CLI flag. The runner
   resolves the effective value; `compare` applies `passed = mismatch_percent <= tolerance`.
   `threshold` (per-pixel, 0..1) follows the same override pattern and is **not** conflated
   with `tolerance`.
7. **`Action` is a data model in `config`; execution is in `capture`.** Supported `kind` values:
   `click`, `hover`, `scroll_to`, `scroll_by`, `fill`, `press`, `select`, `wait`, `open`, `reload`.
   They are written in a short YAML form (`- click: "#sel"`, `- fill: ["#sel", "text"]`,
   `- reload: {}`) that `load_config` parses into `Action(kind, target, value)`;
   `capture` executes each via Playwright.
8. **`runner` and `capture` import 4 of `config`'s 6 types — by design.** `config` is a single
   domain dictionary of models, while `runner` (orchestrator) and `capture` (engine) work with all
   of those models by role. Cell boundaries are drawn by responsibility (data / compare / report /
   capture / orchestration / CLI), not by import count, so the high coupling is intentional.

## Implementation order (leaves → root)

| # | Cell | Reason |
|---|------|--------|
| 1 | `peeksy/config` | Leaf — no Imports. Owns the config data model (`Viewport`, `Action`, `Component`, `Page`, `Suite`) + loader consumed by everyone. |
| 2 | `peeksy/compare` | Leaf — no Imports. Operates on image paths + floats; owns pixelmatch. |
| 3 | `peeksy/reporting` | Leaf — no Imports. `Outcome` is primitives-only; owns Allure. |
| 4 | `peeksy/capture` | Depends on `config` (`Component`, `Viewport`, `Page`, `Action`). Owns Playwright + action execution. |
| 5 | `peeksy/runner` | Depends on `config`, `capture`, `compare`, `reporting`. Orchestration. |
| 6 | `peeksy/cli` | Depends on `config`, `runner`. Typer facade + console entry point. |

Leaves 1–3 are independent and may be implemented in parallel; 4 follows 1; 5 follows 1–4; 6 follows 1 and 5.

## Dependency map

```
 config ◄──── capture
   ▲            ▲
   │            │
   │            │
 compare ◄── runner ──► reporting
   ▲            ▲            ▲
   │            │            │
   └────────────┴────────────┘
                │
              cli ──► config, runner
```

Import edges (no cycles):

```
capture  ← Imports.Types[Component, Viewport, Page, Action]            from peeksy/config
runner   ← Imports.Types[Suite, Page, Component, Viewport]             from peeksy/config
runner   ← Imports.Types[CaptureSession]                               from peeksy/capture
runner   ← Imports.Types[compare, ComparisonResult]                    from peeksy/compare
runner   ← Imports.Types[Outcome, write_results, build_report]         from peeksy/reporting
cli      ← Imports.Types[load_config, Suite]                           from peeksy/config
cli      ← Imports.Types[run_generate, run_test, run_report]           from peeksy/runner
```

---

# Cell 1 — `peeksy/config`

## CODEMANIFEST

```yaml
Usages:
  pydantic_config: |
    Config models are Pydantic v2 BaseModel records. Fields are immutable where practical.
    The site is a folder; `load_config` reads suite.yml plus every pages/*/page.yml and
    its sibling component *.yml files, and validates everything through the models. A
    malformed or invalid file must raise a Pydantic ValidationError surfaced as a
    human-readable message.
    Component.name is derived from its filename (without .yml); Page.name from its
    folder name. Component.name must be unique WITHIN a page (the baseline path and
    testCaseId are namespaced by page) — duplicates inside one page are a validation error.
    threshold (0..1) is the per-pixel sensitivity forwarded to pixelmatch; tolerance
    is the allowed mismatch percent that decides pass/fail. Both accept a per-component
    override where None means "inherit the suite default".
    `Action` setup lists use a short YAML form parsed into Action(kind, target, value):
    a single string is the target for click/hover/scroll_to or the value for press/scroll_by/open;
    a list is [target, value] for fill/select (and optionally press); wait takes a
    selector (appear), {selector: ..., hidden: true} (disappear), a millisecond number (pause),
    or nothing (default stabilization); open takes a URL to navigate to as the value.
    Page.wait_until selects the navigation wait strategy — allowed values: networkidle
    (the default), domcontentloaded, load; anything else is a validation error. Pages with
    long-polling/websockets/constant analytics never reach networkidle and should use
    domcontentloaded plus explicit wait actions in setup.
    Page.components are always kept in name-sorted order — components are captured in that
    deterministic order regardless of filesystem file ordering.
    A component's setup is SELF-SUFFICIENT: it must not rely on side effects left by previously
    captured components (open menus, scroll position, hovers); when a component needs a clean
    page, it starts its setup with reload (written as `- reload: {}`, no target, no value).
    Page.url and a leading open action are mutually exclusive: url = None requires setup to
    START with an open action (the deep-link flow), and a set url forbids open as the first
    setup action — a model_validator rejects both violations so the page is never navigated
    twice and never left without a start URL.
    Relative baseline_path/results_path/report_path in suite.yml resolve against the SITE
    FOLDER (load_config normalizes them to absolute paths), so the suite behaves identically
    no matter which working directory peeksy is invoked from; absolute paths pass through
    unchanged.

Annotations: |
  Config cell — validated YAML configuration model for a peeksy site (variant D layout).

  Use `pydantic_config` for model definitions, the site-folder discovery rules, and validation.
  Do not conflate threshold (per-pixel sensitivity) with tolerance (allowed mismatch %).
  Effective threshold/tolerance are resolved downstream as: component override ?? suite default.
  `Action` only describes what to do; it is executed by the capture cell.

---

"Viewport(width: int, height: int)":
  location: models.py
  annotations: |
    A single viewport dimension in CSS pixels.

    `width`: viewport width in CSS pixels
    `height`: viewport height in CSS pixels

    Use `pydantic_config` for the model definition.
  properties:
    "width -> int": |
      Viewport width in CSS pixels.
    "height -> int": |
      Viewport height in CSS pixels.

"Action(kind: str, target: str | None, value: str | None)":
  location: models.py
  annotations: |
    One setup action to perform on a page or component before a screenshot.

    `kind`: one of click, hover, scroll_to, scroll_by, fill, press, select, wait, open, reload
    `target`: CSS selector of the element the action targets; None when the action needs no element
    `value`: auxiliary value whose meaning depends on `kind` — fill/press/select text/key/option, scroll_by pixels, wait milliseconds-or-mode, open a URL; None when not applicable

    `Action` is data only — it carries no behaviour. The capture cell interprets each kind
    via Playwright. The short YAML form is parsed into this model by `load_config`
    per `pydantic_config`. Per-kind argument rules: click/hover/scroll_to take a `target`;
    scroll_by takes pixel `value` (or [x, y]); fill/select take [target, value]; press takes a
    key `value` (optionally [target, key]); wait takes a selector `target` (appear),
    {selector, hidden} (disappear), a millisecond `value` (pause), or nothing (default stabilization);
    open takes a URL `value` and targets no element; reload re-navigates the current URL and
    takes neither `target` nor `value` (use it to start a component's setup from a clean page).

    Requirements:
    - click/hover/scroll_to: `target` = selector, `value` = None
    - fill/select: `target` = selector, `value` = text/option to enter or pick
    - press: `value` = a Playwright key name ("Enter", "Tab", ...); `target` optional (element to press on)
    - scroll_by: `value` = pixels ("300") or "[x, y]"
    - wait: `value` = milliseconds ("500"), "hidden" (with a `target` selector), or None (default stabilization)
    - open: `value` = URL to navigate the page to; `target` = None
    - reload: `target` = None, `value` = None (reload the currently open page)

    Use `pydantic_config` for the model definition.
  properties:
    "kind -> str": |
      One of click, hover, scroll_to, scroll_by, fill, press, select, wait, open, reload.
    "target -> str | None": |
      CSS selector of the action target; None when no element is needed.
    "value -> str | None": |
      Auxiliary value (text/key/option/pixels/milliseconds/mode/URL); meaning depends on kind; None when not applicable.

"Component(name: str, selector: str, mask_selectors: list[str], viewports: list[Viewport], threshold: float | None, tolerance: float | None, setup: list[Action])":
  location: models.py
  annotations: |
    Specification of one UI component on a page.

    `name`: component identifier, derived from its filename; unique within its page
    `selector`: CSS selector locating the component element
    `mask_selectors`: CSS selectors of dynamic regions to hide before the shot
    `viewports`: viewports to capture this component at (one baseline/result per viewport)
    `threshold`: per-pixel sensitivity override (None => inherit suite threshold)
    `tolerance`: allowed mismatch % override (None => inherit suite tolerance)
    `setup`: component-level actions to run before this component's shot (e.g. hover, click a tab)

    A component does not carry a URL — that lives on its `Page`. Use `pydantic_config` for the model definition.
  properties:
    "name -> str": |
      Component identifier (from its filename); unique within its page.
    "selector -> str": |
      CSS selector locating the component element.
    "mask_selectors -> list[str]": |
      CSS selectors of dynamic regions to hide before the shot.
    "viewports -> list[Viewport]": |
      Viewports to capture this component at.
    "threshold -> float | None": |
      Per-pixel sensitivity override; None inherits the suite default.
    "tolerance -> float | None": |
      Allowed mismatch % override; None inherits the suite default.
    "setup -> list[Action]": |
      Component-level actions to run before the shot.

"Page(name: str, url: str | None, wait_until: str, setup: list[Action], components: list[Component])":
  location: models.py
  annotations: |
    One page of the site: a URL, navigation wait strategy, page-level setup actions, and the components on it.

    `name`: page identifier, derived from its folder name
    `url`: page URL to open before capturing any of its components; None for a deep-link flow where setup starts with an open action
    `wait_until`: navigation wait strategy forwarded to page.goto — "networkidle" (default when omitted in page.yml), "domcontentloaded", or "load"; live pages (long-polling, websockets, constant analytics) should use "domcontentloaded" plus explicit wait actions in setup
    `setup`: page-level actions run once per viewport after navigation (e.g. close cookie banner, log in)
    `components`: components discovered as the sibling *.yml files of this page's page.yml, kept in name-sorted order so capture order is deterministic regardless of filesystem ordering

    Validation: Component.name values MUST be unique within `components` of this page; a
    model_validator rejects duplicates so they cannot collide on the page-namespaced
    baseline path or testCaseId. `wait_until` must be one of networkidle/domcontentloaded/load.
    url and a leading open are mutually exclusive: url = None requires setup[0] to be an open
    action; a set url forbids open as setup[0] — the page is never navigated twice and never
    left without a start URL. Use `pydantic_config` for the model definition.
  properties:
    "name -> str": |
      Page identifier (from its folder name).
    "url -> str | None": |
      Page URL to open before capturing; None for a deep-link flow (setup starts with open).
    "wait_until -> str": |
      Navigation wait strategy: networkidle (default), domcontentloaded, or load.
    "setup -> list[Action]": |
      Page-level actions run once per viewport after navigation.
    "components -> list[Component]": |
      Components on this page (sibling *.yml files), name-sorted for deterministic capture order.

"Suite(name: str, pages: list[Page], baseline_path: str, results_path: str, report_path: str, threshold: float, tolerance: float)":
  location: models.py
  annotations: |
    The whole peeksy configuration loaded from a site folder.

    `name`: suite/site name (used as the Allure suite label)
    `pages`: pages to capture and compare
    `baseline_path`: directory for baseline PNGs (written by generate, read-only for test), organized as {baseline_path}/{page}/{name}_{WxH}.png; relative values resolve against the site folder
    `results_path`: directory for Allure results and current/diff PNGs; relative values resolve against the site folder
    `report_path`: directory for the built HTML report; relative values resolve against the site folder
    `threshold`: suite-default per-pixel sensitivity (0..1) forwarded to pixelmatch
    `tolerance`: suite-default allowed mismatch % — a component PASSES when mismatch% <= tolerance

    The same component name MAY appear on different pages (they are namespaced by page); only
    duplicates within a single page are rejected. Use `pydantic_config` for the model definition.
  properties:
    "name -> str": |
      Suite/site name; used as the Allure suite label.
    "pages -> list[Page]": |
      Pages to capture and compare.
    "baseline_path -> str": |
      Directory for baseline PNGs (organized by page).
    "results_path -> str": |
      Directory for Allure results and current/diff PNGs.
    "report_path -> str": |
      Directory for the built HTML report.
    "threshold -> float": |
      Suite-default per-pixel sensitivity (0..1).
    "tolerance -> float": |
      Suite-default allowed mismatch %.

"load_config(path: str) -> suite: Suite":
  location: loader.py
  annotations: |
    Discover and validate a peeksy site folder.

    `path`: path to the site folder (a suite.yml inside is also accepted)
    `suite`: the validated Suite

    Algorithm:
    1. Resolve the site folder from `path` (if `path` is suite.yml, use its parent)
    2. Read and validate suite.yml for the suite meta (name, paths, threshold, tolerance); normalize relative baseline_path/results_path/report_path to absolute paths against the site folder so the suite is CWD-independent
    3. For each subfolder of pages/, read its page.yml (url, setup) and discover its components as the other *.yml files in that folder
    4. Build `Page` and `Component` models (names derived from folder/filenames) and validate per `pydantic_config`, including per-page name uniqueness
    5. Return the resulting `Suite`; raise on any validation or IO error with a human-readable message

    Use `pydantic_config` for validation rules.

---
Author: Goga
CreatedAt: 13/07/26
Description: |
  Config cell — Pydantic v2 models (Viewport, Action, Component, Page, Suite) and the
  site-folder loader for the variant D layout, including the configurable `threshold`/`tolerance`.
```

## .usages/config.md

````markdown
# config — Loading and Using the peeksy Site Configuration

## Domain

How to load and consume the validated peeksy site configuration (variant D: site folder →
page folder → component file). Target audience: the `runner` and `cli` cells that need a `Suite`.

## Load a suite

```python
from peeksy.config import load_config

suite = load_config("sites/example.com")          # site folder
suite = load_config("sites/example.com/suite.yml")  # or the suite file directly
```

`load_config` raises a Pydantic ValidationError with a human-readable message on a malformed
or invalid site.

## Walk pages and components

```python
for page in suite.pages:
    for component in page.components:
        for viewport in component.viewports:
            ...
        tol = component.tolerance if component.tolerance is not None else suite.tolerance
        thr = component.threshold if component.threshold is not None else suite.threshold
```

- `page.url` is the page to open; `page.setup` runs once per viewport after navigation.
- `url` and a leading `open` are mutually exclusive (validated): `url: null` requires `setup`
  to start with `- open: <url>` (deep-link flow); a set `url` forbids `open` as the first
  action — the page is never navigated twice and never left without a start URL.
- `page.wait_until` selects the navigation wait strategy: `networkidle` (default), `domcontentloaded`, or `load`. Pages with long-polling/websockets/constant analytics never reach `networkidle` — set `wait_until: domcontentloaded` and add explicit `- wait: "#content"` actions in setup.
- `component.setup` runs before that component's shot.
- Per-component `threshold`/`tolerance` override the suite defaults; `None` means inherit.

## Setup actions (short form)

`page.setup` and `component.setup` are lists of actions written in a short YAML form:

```yaml
# page.yml — page-level setup runs once per viewport
# url + a leading open are mutually exclusive:
#   url: https://example.com/            # normal start page (usual case)
#   url: null + first setup action open  # deep-link flow (e.g. after login)
wait_until: domcontentloaded   # optional: networkidle (default) | domcontentloaded | load
setup:
  - open: "https://example.com/login"     # navigate to a URL directly
  - click: "#cookie-accept"               # click an element
  - scroll_to: "#main"                    # scroll an element into view
  - wait: 500                             # pause 500 ms
  - wait: "#loader"                       # wait for an element to appear
  - wait: {selector: "#modal", hidden: true}  # wait for it to disappear
  - wait: {}                              # default stabilization (networkidle + fonts)

# <component>.yml — component-level setup runs before that component's shot
setup:
  - hover: ".menu-trigger"                # hover an element
  - fill: ["#search", "shoes"]            # [target, value]: type into a field
  - press: "Enter"                        # press a key (on the page)
  - press: ["#search", "Enter"]           # press a key on an element
  - select: ["#country", "RU"]            # [target, value]: pick an option
  - scroll_by: 300                        # scroll down 300 px
  - scroll_by: [0, 300]                   # scroll [x, y]
  - reload: {}                            # clean-page isolation before this component's shot
```

- A single string is the `target` for click/hover/scroll_to, or the `value` for press/scroll_by/open.
- A list is `[target, value]` for fill/select (and optionally press).
- `open` navigates the page to its `value` URL (target is unused); useful for redirects or
  deep-linking to a state mid-setup.
- `reload` re-navigates the current URL (`- reload: {}`, no arguments) — use it when a component
  must not inherit side effects (open menus, scroll) from previously captured components.
- `wait` is overloaded by value type (see examples).

**Capture order:** components are captured in **name-sorted** order within a page, regardless of
filesystem file ordering — keep each component's `setup` self-sufficient; add `- reload: {}`
at its start when it needs a clean page.

## Naming and uniqueness

- `Component.name` comes from its filename; `Page.name` from its folder name.
- Component names must be unique **within a page** (they are namespaced by page in the
  baseline path and `testCaseId`). The same name on different pages is fine.

## Paths

- `suite.baseline_path` — baseline PNGs, organized as `{baseline_path}/{page}/{name}_{WxH}.png`
- `suite.results_path` — Allure results + current/diff PNGs
- `suite.report_path` — built HTML report
- Relative paths in `suite.yml` resolve against the **site folder** (`load_config` normalizes
  them to absolute), so `peeksy generate`/`test` behave identically from any working directory:
  `baseline_path: baselines` next to `sites/example.com/suite.yml` means `sites/example.com/baselines/`.
  Absolute paths pass through unchanged.
````

---

# Cell 2 — `peeksy/compare`

## CODEMANIFEST

```yaml
Usages:
  image_diff: .goga/usages/cooks/image-diff.md

Annotations: |
  Compare cell — pixelmatch-based comparison of two component screenshots.

  Use `image_diff` for the pixelmatch call signature and diff-overlay handling.
  threshold is the per-pixel sensitivity (0..1) forwarded to pixelmatch; tolerance is the
  allowed mismatch % that decides passed. A size change is a regression (mismatch 100%).

---

"ComparisonResult(passed: bool, mismatch_percent: float, diff_path: str | None)":
  location: result.py
  annotations: |
    Verdict of one image comparison.

    `passed`: True when `mismatch_percent` is within the allowed tolerance
    `mismatch_percent`: percentage of differing pixels (0..100)
    `diff_path`: path to the diff overlay image; None when the comparison passed (no diff written)

    Use `image_diff` for the meaning of `mismatch_percent` and `diff_path`.
  properties:
    "passed -> bool": |
      True when mismatch_percent is within the allowed tolerance.
    "mismatch_percent -> float": |
      Percentage of differing pixels (0..100).
    "diff_path -> str | None": |
      Path to the diff overlay image; None when the comparison passed.

"compare(baseline: str, current: str, diff_dir: str, threshold: float, tolerance: float) -> result: ComparisonResult":
  location: compare.py
  annotations: |
    Compare a baseline PNG against a current PNG and decide whether the component regressed.

    `baseline`: path to the baseline PNG
    `current`: path to the current PNG
    `diff_dir`: directory to write the diff overlay into (only when not passed)
    `threshold`: per-pixel color sensitivity (0..1) forwarded to pixelmatch
    `tolerance`: allowed mismatch % — passed is True when mismatch% <= tolerance
    `result`: the ComparisonResult verdict

    Algorithm:
    1. Load `baseline` and `current`, convert both to RGBA per `image_diff`
    2. If sizes differ, return a failed `ComparisonResult` with mismatch_percent 100.0 and diff_path None
    3. Run pixelmatch with `threshold` and includeAA to count mismatched pixels per `image_diff`
    4. Compute mismatch_percent = mismatched / total * 100
    5. Set passed = mismatch_percent <= `tolerance`
    6. If not passed, save the diff overlay into `diff_dir` and set diff_path; otherwise diff_path None
    7. Return the `ComparisonResult`

    Use `image_diff` for the pixelmatch call and diff-overlay handling.

---
Author: Goga
CreatedAt: 13/07/26
Description: |
  Compare cell — pixelmatch comparison producing a pass/fail verdict, mismatch %,
  and diff overlay; `tolerance` decides the verdict.
```

## .usages/compare.md

````markdown
# compare — Comparing Two Component Screenshots

## Domain

How to compare a baseline PNG against a current PNG and read the verdict. Target
audience: the `runner` cell.

## Compare two images

```python
from peeksy.compare import compare

result = compare(
    baseline="baselines/home/header_1280x720.png",
    current="results/home/header_1280x720.current.png",
    diff_dir="results/home",
    threshold=0.1,
    tolerance=0.5,
)
```

## Read the verdict

```python
if result.passed:
    ...  # mismatch_percent <= tolerance
else:
    diff = result.diff_path  # path to the red-overlay diff PNG
```

- `threshold` (0..1) is the per-pixel sensitivity forwarded to pixelmatch.
- `tolerance` is the allowed mismatch % that decides `passed`.
- `diff_path` is set only when the comparison failed; a size change is a definite failure (100%).
````

---

# Cell 3 — `peeksy/reporting`

## CODEMANIFEST

```yaml
Usages:
  allure: .goga/usages/cooks/allure.md

Annotations: |
  Reporting cell — produce Allure result data and build the browsable HTML report.

  Use `allure` for the Allure result model, attachment handling, and the external allure CLI.
  One test result is written per `Outcome`. status PASSED/FAILED = visual verdict; BROKEN =
  infrastructure failure, carried with an error message. Attachments are written only for
  non-None image paths, so a BROKEN outcome with no current_path (or no baseline_path)
  simply omits that attachment; mismatch_percent is None for BROKEN (no comparison happened),
  never a fake 0.0 that would read as a perfect match in numeric filtering. The Allure
  display name is {suite} / {page} / {name} [{viewport}],
  testCaseId is peeksy::{suite}::{page}::{name}[{viewport}] (suite+page-namespaced AND
  viewport-suffixed so the same component name on different pages, different sites, or at
  different viewports never collapses), and the Allure suite label
  carries the real site name from the `Outcome`.

---

"Outcome(suite: str, page: str, name: str, viewport: str, status: str, mismatch_percent: float | None, baseline_path: str | None, current_path: str | None, diff_path: str | None, error: str | None)":
  location: outcome.py
  annotations: |
    One reportable result for a single (page, component, viewport) check.

    `suite`: suite/site name — part of testCaseId and the Allure suite label
    `page`: page name
    `name`: component name
    `viewport`: viewport label, e.g. "1280x720"
    `status`: "PASSED", "FAILED", or "BROKEN"
    `mismatch_percent`: mismatch percentage (0..100); None for BROKEN (no comparison happened)
    `baseline_path`: path to the baseline PNG attachment; None when no baseline exists (BROKEN)
    `current_path`: path to the current PNG attachment; None when capture failed (BROKEN)
    `diff_path`: path to the diff PNG attachment; None when not produced (passed or BROKEN)
    `error`: human-readable reason for a BROKEN status; None for PASSED/FAILED

    Use `allure` for how `status` maps to the Allure Status.
  properties:
    "suite -> str": |
      Suite/site name; keys testCaseId and the Allure suite label.
    "page -> str": |
      Page name.
    "name -> str": |
      Component name.
    "viewport -> str": |
      Viewport label, e.g. "1280x720".
    "status -> str": |
      "PASSED", "FAILED", or "BROKEN".
    "mismatch_percent -> float | None": |
      Mismatch percentage (0..100); None for BROKEN (no comparison happened).
    "baseline_path -> str | None": |
      Path to the baseline PNG attachment; None when no baseline exists (BROKEN).
    "current_path -> str | None": |
      Path to the current PNG attachment; None when capture failed (BROKEN).
    "diff_path -> str | None": |
      Path to the diff PNG attachment; None when not produced.
    "error -> str | None": |
      Reason for a BROKEN status (e.g. "baseline not found", "selector not found"); None otherwise.

"write_results(outcomes: list[Outcome], results_dir: str)":
  location: writer.py
  annotations: |
    Stage 1 — write Allure result JSON and attachments for a set of outcomes.

    `outcomes`: outcomes to report, one per (page, component, viewport)
    `results_dir`: directory to populate with result JSON and attachment files

    Algorithm:
    1. For each `Outcome`, derive a stable testCaseId/historyId as peeksy::{suite}::{page}::{name}, the display name as {suite} / {page} / {name} [{viewport}], and the Allure suite label from the `Outcome` suite field per `allure`
    2. For each non-None path among baseline_path, current_path, diff_path, copy the PNG into `results_dir` as an attachment; skip None paths (a BROKEN outcome may omit current_path or baseline_path)
    3. Write one result JSON with status mapped from the `Outcome` status per `allure`, attaching the copied PNGs
    4. Append statusDetails with the mismatch percent when FAILED, or with the error message when BROKEN (mismatch_percent is None — never render it for BROKEN)

    Use `allure` for the result model and attachment conventions.

"build_report(results_dir: str, report_dir: str)":
  location: report.py
  annotations: |
    Stage 2 — build the browsable Allure HTML report.

    `results_dir`: directory populated by `write_results`
    `report_dir`: directory to write the HTML report into

    Algorithm:
    1. Verify the allure CLI is on PATH via shutil.which("allure"); if missing, raise a human-readable error with install instructions (brew/sdkman, requires JDK) instead of letting subprocess fail with FileNotFoundError
    2. Invoke the external allure CLI to generate the report from `results_dir` into `report_dir` with --clean per `allure`

    Use `allure` for the CLI invocation.
    Constraints: requires the allure CLI (Java/JDK) on PATH; raises a human-readable error when absent.

---
Author: Goga
CreatedAt: 13/07/26
Description: |
  Reporting cell — Allure result writer and HTML report builder; one result per
  (page, component, viewport) with baseline/current/diff attachments.
```

## .usages/reporting.md

````markdown
# reporting — Allure Results and HTML Report

## Domain

How to turn component outcomes into Allure result data and build the browsable HTML
report. Target audience: the `runner` cell.

## Stage 1 — write results

```python
from peeksy.reporting import write_results, Outcome

outcomes = [
    Outcome(suite="example.com", page="home", name="header", viewport="1280x720", status="FAILED",
            mismatch_percent=2.34,
            baseline_path="baselines/home/header_1280x720.png",
            current_path="results/home/header_1280x720.current.png",
            diff_path="results/home/header_1280x720.diff.png",
            error=None),
    # BROKEN: capture failed — no current PNG, no comparison, mismatch_percent is None
    Outcome(suite="example.com", page="home", name="sidebar", viewport="1280x720", status="BROKEN",
            mismatch_percent=None,
            baseline_path="baselines/home/sidebar_1280x720.png",
            current_path=None,
            diff_path=None,
            error="selector '.sidebar' not found within timeout"),
]
write_results(outcomes, results_dir="results")
```

- One result JSON is written per `Outcome`; the display name is `{suite} / {page} / {name} [{viewport}]`.
- `testCaseId`/`historyId` are `peeksy::{suite}::{page}::{name}[{viewport}]` (suite+page-namespaced,
  viewport-suffixed — the same component name on different pages, different sites, or at different
  viewports never collapses).
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
````

---

# Cell 4 — `peeksy/capture`

## CODEMANIFEST

```yaml
Imports:
  - Types:
      - Component
      - Viewport
      - Page
      - Action
    From: peeksy/config

Usages:
  playwright: .goga/usages/cooks/playwright.md

Annotations: |
  Capture cell — deterministic element-level screenshots via Playwright, including the
  execution of page/component `Action` setup steps.

  Use `playwright` for the Playwright lifecycle, capture routine, action execution, masking,
  and determinism rules. One browser and one context (device_scale_factor=1) are reused across
  the whole run. `Component`, `Viewport`, `Page`, and `Action` come from Imports.
  Capture is split: open_page navigates and runs the page setup once per viewport;
  capture_component runs the component setup, masked, and shoots.
  Masking lays an opaque gray overlay (::after) over each masked element so the masked area is
  pixel-identical across runs regardless of what is underneath, while keeping the layout box
  (never display: none, which would reflow neighbors and shift the component).
  Each `Action` is interpreted via Playwright per `playwright` according to its kind:
  click/hover/fill/press/select act on a located element, scroll_to/scroll_by move the page,
  open navigates to the URL given as its value and reload re-navigates the current URL — both
  with the same wait_until + fonts determinism as open_page — and wait blocks until an element
  appears/disappears, a millisecond elapses, or the default stabilization completes.
  A component selector may be a Playwright piercing selector (e.g. my-widget >> button.save,
  which crosses shadow-DOM boundaries) or address a component inside an <iframe> (resolved via
  frame_locator); capture_component localizes it the same way as a plain CSS selector.
  mask_selectors are located with the SAME locate helper as the component selector — plain CSS,
  piercing, or inside an <iframe> — so any dynamic zone reachable from the component is maskable
  (e.g. my-widget >> form.order .date masks a date inside the same shadow DOM).

---

"CaptureSession()":
  location: session.py
  annotations: |
    Owns the Playwright browser/context lifecycle for one run.

    Use `playwright` for the browser/context setup and teardown.
    Constraints: open_page/capture_component require open() first; the session must be close()d after use.
  methods:
    "open()": |
      Launch a headless Chromium browser and a single context with device_scale_factor=1 and one page per `playwright`.
    "open_page(page: Page, viewport: Viewport)": |
      Navigate to a page at a viewport and run its page-level setup once.

      `page`: the page spec (url, setup) from Imports
      `viewport`: the viewport to set before any component on this page is captured

      Algorithm:
      1. Set the page viewport to `viewport` per `playwright`
      2. If page.url is not None, navigate to it with wait_until=page.wait_until (networkidle by default; domcontentloaded/load for live pages) per `playwright`; when url is None the first setup action (guaranteed to be open by validation) performs the navigation
      3. Disable animations/transitions and wait for document.fonts.ready per `playwright`
      4. For each `Action` in page.setup, execute it via Playwright according to its kind

      Use `playwright` for navigation, determinism, and action execution.
      Constraints: call once per (page, viewport); captures for that pair happen via capture_component afterwards.
    "capture_component(component: Component, out_path: str) -> png_path: str": |
      Capture a deterministic screenshot of one component on the currently open page.

      `component`: the component spec (selector, mask_selectors, setup) from Imports
      `out_path`: file path to write the PNG to
      `png_path`: the written PNG path (equals `out_path`)

      Algorithm:
      1. For each `Action` in component.setup, execute it via Playwright according to its kind
      2. For every mask selector of `component` (located with the same locate helper as the component selector — plain CSS, piercing, or inside an <iframe>), lay an opaque gray overlay (::after) over the matched elements per `playwright` — a solid overlay yields pixel-identical masks regardless of the underlying content, while preserving the layout box (never display: none)
      3. Locate the `component` selector (first match) — a plain CSS selector, a piercing selector crossing shadow-DOM boundaries, or a selector inside an <iframe> via frame_locator — wait for visible, and screenshot into `out_path`
      4. Return `out_path`

      Use `playwright` for the capture routine, action execution, and masking.
      Constraints: idempotent — two captures of the same `Component` on the same open page produce pixelmatch-clean images.
    "close()": |
      Tear down the context and browser per `playwright`.

---
Author: Goga
CreatedAt: 13/07/26
Description: |
  Capture cell — Playwright CaptureSession with two-level setup: open_page navigates and
  runs page setup once per viewport; capture_component runs component setup, masks, and shoots.
```

## .usages/capture.md

````markdown
# capture — Deterministic Component Screenshots

## Domain

How to capture deterministic element-level screenshots with Playwright, including the
page/component setup actions. Target audience: the `runner` cell.

## Capture a run

```python
from peeksy.capture import CaptureSession

session = CaptureSession()
session.open()
try:
    for page in suite.pages:
        # viewports needed by this page's components (inline union)
        viewports = {vp for c in page.components for vp in c.viewports}
        for viewport in viewports:
            session.open_page(page, viewport)        # navigate + page setup, once
            for component in page.components:
                if viewport in component.viewports:
                    session.capture_component(
                        component, out_path=f"baselines/{page.name}/{component.name}_1280x720.png")
finally:
    session.close()
```

- One browser and one context (device_scale_factor=1) are reused across the whole run.
- `open_page` navigates and runs `page.setup` once per viewport; call it before `capture_component` for that (page, viewport).
- `capture_component` runs `component.setup`, masks, and writes the PNG to `out_path`.
- `open_page`/`capture_component` require `open()` first; always `close()` the session after use.
- Captures are idempotent: same component on the same open page ⇒ pixelmatch-clean images.
- Mask selectors are covered with an opaque gray overlay (`::after`, never `display: none`) so the masked area is pixel-identical across runs while preserving layout; masks are located with the same helper as the component selector (plain CSS, piercing `>>`, or inside an `<iframe>`).
````

---

# Cell 5 — `peeksy/runner`

## CODEMANIFEST

```yaml
Imports:
  - Types:
      - Suite
      - Page
      - Component
      - Viewport
    From: peeksy/config
  - Types:
      - CaptureSession
    From: peeksy/capture
  - Types:
      - compare
      - ComparisonResult
    From: peeksy/compare
  - Types:
      - Outcome
      - write_results
      - build_report
    From: peeksy/reporting

Usages:
  run_policy: |
    Orchestration rules for a peeksy run. generate writes baselines only. test is
    read-only on baselines and returns exit_code 0 when every component PASSES, otherwise 1.
    Capture/infrastructure failures become Outcome status BROKEN, not visual regressions.
    A missing baseline file is also BROKEN ("baseline not found; run peeksy generate"),
    never a visual regression. Every BROKEN Outcome carries a human-readable error; its
    current_path/baseline_path are None when the corresponding image does not exist.
    Effective threshold/tolerance per component = component override ?? suite default.
    Paths are namespaced by page: baseline {baseline_path}/{page}/{name}_{WxH}.png,
    current {results_path}/{page}/{name}_{WxH}.current.png, diff {results_path}/{page}/{name}_{WxH}.diff.png.
    Capture is grouped by (page, viewport): open_page is called once per (page, viewport),
    then each component at that viewport is captured — page setup never repeats per component.
    Components are processed in name-sorted order (deterministic regardless of filesystem
    ordering); a component's setup is self-sufficient and must not rely on side effects of
    previously captured components — a component needing a clean page starts its setup with reload.
    If open_page fails, every (component, viewport) on that page becomes BROKEN with the
    page-setup error. pages filters by page name, components by component name; both None ⇒ all.
    Before writing results, test clears the results_path of prior *-result.json and
    attachment files so consecutive runs never silently mix.

Annotations: |
  Runner cell — orchestrates generate/test/report over a Suite of pages.

  Use `run_policy` for orchestration rules and path conventions.
  `Suite`, `Page`, `Component`, `Viewport` come from the config cell; `CaptureSession` from capture;
  `compare` and `ComparisonResult` from compare; `Outcome`, `write_results`, `build_report` from reporting.

---

"run_generate(suite: Suite, pages: list[str] | None, components: list[str] | None)":
  location: runner.py
  annotations: |
    Capture and store baselines for the selected pages/components.

    `suite`: the loaded configuration
    `pages`: page names to limit to (None => all)
    `components`: component names to limit to (None => all)

    Algorithm:
    1. Filter suite.pages by `pages` and each page's components by `components` per `run_policy` (None => all)
    2. Open a `CaptureSession`
    3. For each filtered `Page`:
       a. Compute the set of Viewports needed = union of viewports across its filtered components
       b. For each `Viewport`: open_page(page, viewport), then for each component that includes this `Viewport`, capture_component into {baseline_path}/{page}/{name}_{WxH}.png per `run_policy`
    4. Close the `CaptureSession`

    Use `run_policy` for path conventions and capture grouping.
    Use `CaptureSession` from Imports for capture.

"run_test(suite: Suite, pages: list[str] | None, components: list[str] | None) -> exit_code: int":
  location: runner.py
  annotations: |
    Capture, compare against baselines, and write Allure outcomes.

    `suite`: the loaded configuration
    `pages`: page names to limit to (None => all)
    `components`: component names to limit to (None => all)
    `exit_code`: 0 when every component PASSES, otherwise 1

    Algorithm:
    1. Filter suite.pages by `pages` and each page's components by `components` per `run_policy` (None => all)
    2. Open a `CaptureSession`; collect `Outcome`s
    3. For each filtered `Page`:
       a. Compute the set of Viewports needed = union of viewports across its filtered components
       b. For each `Viewport`:
          i. Try: open_page(page, viewport)
          ii. Except: append a BROKEN `Outcome` (suite = suite.name, page, name, viewport, error "page setup failed: ...", current_path None) for every component at this viewport per `run_policy`; continue to the next viewport
          iii. For each component at this `Viewport`:
               - Try: capture_component -> current {results_path}/{page}/{name}_{WxH}.current.png
               - Except capture error: append a BROKEN `Outcome` with error and current_path None; continue
               - If baseline {baseline_path}/{page}/{name}_{WxH}.png does not exist: append a BROKEN `Outcome` with error "baseline not found; run peeksy generate" per `run_policy`; continue
               - Resolve effective threshold/tolerance = component override ?? `suite` default per `run_policy`
               - `compare` baseline vs current with the resolved thresholds -> `ComparisonResult`; status = PASSED if it passed, else FAILED
               - Append a PASSED/FAILED `Outcome` (suite = suite.name, page, name, viewport, status, mismatch_percent, baseline/current/diff paths, error None)
    4. Clear the `suite` results_path of prior *-result.json and attachment files per `run_policy`
    5. `write_results` the outcomes into the `suite` results_path
    6. Return `exit_code` 0 if all outcomes PASSED else 1

    Use `run_policy` for orchestration rules, path conventions, and capture grouping.
    Use `compare`, `ComparisonResult`, `Outcome`, `write_results` from Imports.

"run_report(suite: Suite)":
  location: runner.py
  annotations: |
    Build the Allure HTML report from the results directory.

    `suite`: the loaded configuration (provides results_path and report_path)

    Algorithm:
    1. Call `build_report` with the `suite` results_path and report_path

    Use `run_policy` for the report stage.
    Use `build_report` from Imports.

---
Author: Goga
CreatedAt: 13/07/26
Description: |
  Runner cell — orchestrates generate/test/report over pages: two-level capture (open_page +
  capture_component), compare, and Allure reporting, with CI-friendly exit codes and BROKEN handling.
```

## .usages/runner.md

````markdown
# runner — Orchestrating generate / test / report

## Domain

How to run a peeksy generate/test/report pass over a loaded `Suite` of pages. Target audience:
the `cli` cell.

## Generate baselines

```python
from peeksy.config import load_config
from peeksy.runner import run_generate

suite = load_config("sites/example.com")
run_generate(suite, pages=None, components=None)             # everything
run_generate(suite, pages=["home"], components=["header"])   # one component on one page
```

`generate` writes baseline PNGs into `suite.baseline_path` as `{page}/{name}_{WxH}.png`.

## Test against baselines

```python
from peeksy.runner import run_test

exit_code = run_test(suite, pages=["home"], components=["header", "sidebar"])
```

- `test` is read-only on baselines.
- Returns `0` when every component PASSES, otherwise `1` (CI-friendly).
- Capture is grouped by (page, viewport): page setup runs once per viewport, not per component.
- Infrastructure failures (page did not load, selector missing) become `BROKEN`, not regressions.
- A component with no baseline file is reported as `BROKEN` ("baseline not found; run `peeksy generate`"), not as a regression.
- `BROKEN` outcomes carry a human-readable `error`; their image paths are `None` where no file exists.
- The results directory is cleared of prior `*-result.json`/attachment files before each `test` write, so consecutive runs never silently mix.

## Build the report

```python
from peeksy.runner import run_report

run_report(suite)
```

Builds the Allure HTML into `suite.report_path` (requires the `allure` CLI).
````

---

# Cell 6 — `peeksy/cli`

## CODEMANIFEST

```yaml
Imports:
  - Types:
      - load_config
      - Suite
    From: peeksy/config
  - Types:
      - run_generate
      - run_test
      - run_report
    From: peeksy/runner

Usages:
  typer: |
    CLI commands are Typer commands on a single Typer app. --config takes the site folder
    (or its suite.yml). --page and --component are repeatable filters (list[str] | None);
    both applied as an AND. Commands load the config via `load_config` and delegate to the runner.
    test prints a one-line summary and then raise typer.Exit(code=exit_code) (never sys.exit)
    so CI fails on regression and pytest can still intercept the exit.

Annotations: |
  CLI cell — Typer facade for the peeksy commands.

  Use `typer` for command definitions and the repeatable --page/--component options.
  `load_config` and `Suite` come from the config cell; `run_generate`, `run_test`, `run_report` from runner.

---

"generate(config: str, page: list[str] | None, component: list[str] | None)":
  location: app.py
  annotations: |
    peeksy generate command — capture and store baselines.

    `config`: path to the site folder (or its suite.yml)
    `page`: repeatable page name filter (None => all)
    `component`: repeatable component name filter (None => all)

    Algorithm:
    1. `load_config` `config` into a `Suite`
    2. Call `run_generate` with the `Suite`, `page`, and `component`

    Use `typer` for the command and --page/--component options.
    Use `load_config` and `run_generate` from Imports.

"test(config: str, page: list[str] | None, component: list[str] | None)":
  location: app.py
  annotations: |
    peeksy test command — compare against baselines and fail CI on regression.

    `config`: path to the site folder (or its suite.yml)
    `page`: repeatable page name filter (None => all)
    `component`: repeatable component name filter (None => all)

    Algorithm:
    1. `load_config` `config` into a `Suite`
    2. Call `run_test` with the `Suite`, `page`, and `component` to get the exit code
    3. Print a one-line summary derived from the exit code ("all components passed" when 0, otherwise "regression or infrastructure failure detected — see the Allure report")
    4. raise typer.Exit(code=exit_code) per `typer` so CI fails on any regression

    Use `typer` for the command, the --page/--component options, and typer.Exit.
    Use `load_config` and `run_test` from Imports.

"report(config: str)":
  location: app.py
  annotations: |
    peeksy report command — build the Allure HTML report.

    `config`: path to the site folder (or its suite.yml)

    Algorithm:
    1. `load_config` `config` into a `Suite`
    2. Call `run_report` with the `Suite`
    3. If `run_report` raises the missing-allure-CLI error, print a human-readable message with install instructions (brew/sdkman, requires JDK) and exit non-zero instead of surfacing a Python traceback

    Use `typer` for the command.
    Use `load_config` and `run_report` from Imports.

"main()":
  location: app.py
  annotations: |
    Entry point of the peeksy console script.

    Algorithm:
    1. Run the Typer app per `typer`

    Use `typer` for the app entry point.

---
Author: Goga
CreatedAt: 13/07/26
Description: |
  CLI cell — Typer facade with generate/test/report commands, --page/--component filters,
  and the peeksy console entry point.
```

## .usages/cli.md

````markdown
# cli — Running the peeksy CLI

## Domain

How to invoke the `peeksy` commands from the shell. Target audience: the end user and CI.

## Commands

```bash
# Capture baselines for all pages/components
peeksy generate --config sites/example.com

# Capture baselines for selected pages/components (both flags repeatable)
peeksy generate --config sites/example.com --page home --component header --component sidebar

# Compare against baselines; exit code != 0 on any regression (CI-friendly)
peeksy test --config sites/example.com
peeksy test --config sites/example.com --page home --component header

# Build the browsable Allure HTML report
peeksy report --config sites/example.com
```

- `--config` takes the site folder (or its `suite.yml`).
- `--page` and `--component` are repeatable and combine as an AND; omit them to process everything.
- `test` is read-only on baselines, prints a one-line summary, and raises `typer.Exit` with a non-zero code on any regression or BROKEN.
- Infrastructure failures are reported as `BROKEN`, not as visual regressions.
- `report` requires the external `allure` CLI (Java/JDK) on PATH; if it is missing, peeksy prints a clear install message instead of a traceback.
````

---

# Verification checklist

## Acceptance criteria coverage (from `docs/tasks/peeksy-cli.md`)

- [x] `generate` (no flags) creates baselines for all pages/components; re-run is pixelmatch-clean → `run_generate` + `CaptureSession` idempotency.
- [x] `generate --page P --component a --component b` limits to selected → `run_generate(pages=..., components=...)` + `generate` repeatable flags.
- [x] `test` compares all, attaches baseline/current/diff, exit 0/≠0 → `run_test` + `write_results` + `test` exits with `exit_code`.
- [x] `test --component X` limits to X → `run_test(components=[...])` (matches X on every page).
- [x] Per-viewport separate baseline + separate Allure result; only the regressing viewport is FAILED → `run_test` iterates `(Page, Component, Viewport)`; `Outcome` per triple.
- [x] ~2px shift detected as FAILED (mismatch > tolerance) → `compare` + configurable `tolerance`.
- [x] Infrastructure errors → `Status.BROKEN` → `run_test` step 3.b.ii/3.b.iii + `Outcome.status`.
- [x] `report` builds browsable HTML → `run_report` + `build_report`.
- [x] Invalid YAML → clear Pydantic error → `load_config` raises.
- [x] Tool's own tests pass locally → out of architecture scope; covered by `pytest + pytest-playwright` in the task doc.

## Architecture decisions (design + review passes)

Decisions folded into the CODEMANIFESTs and `.usages` above:

- [x] **Three-level config (variant D)** — site folder → page folder → component file; `Suite` holds `pages: list[Page]`, `url` on the page, names from folder/filenames, component names unique within a page (`config`).
- [x] **Two-level setup actions** — `Page.setup` (once per viewport) + `Component.setup` (per component); `Action` carries 8 kinds (click/hover/scroll_to/scroll_by/fill/press/select/wait) in a short YAML form, executed by `capture` (`config`, `capture`).
- [x] **Split capture** — `open_page` navigates + page setup once per `(page, viewport)`; `capture_component` does component setup + mask + shot (`capture`, `runner`).
- [x] **BROKEN no longer requires an image** — `Outcome.baseline_path`/`current_path` are `str | None`; `Outcome.error: str | None` carries the reason; `write_results` attaches only existing PNGs (`reporting`, `runner`).
- [x] **Missing baseline is BROKEN, not FAILED** — `run_test` checks baseline existence before `compare` and emits `error="baseline not found; run 'peeksy generate'"` (`runner`).
- [x] **Page-grouped capture** — `open_page` is called once per `(page, viewport)`; a page-setup failure marks every component at that viewport BROKEN (`runner`).
- [x] **Masking is an opaque gray overlay (`::after`)** — never `display: none` — so the masked area is pixel-identical across runs regardless of underlying content, while keeping the layout box (`capture`).
- [x] **`test` exits via `typer.Exit`** — `raise typer.Exit(code=exit_code)` after a one-line summary; never `sys.exit` (`cli`).
- [x] **Missing `allure` CLI is a clean error** — `build_report` checks `shutil.which("allure")`; the `report` command prints a clear message instead of a traceback (`reporting`, `cli`).
- [x] **Results dir cleared per run** — `run_test` removes prior `*-result.json`/attachment files before writing (`runner`).
- [x] **Page-namespaced identity** — display name `{page} / {name} [{viewport}]`, `testCaseId` `peeksy::{page}::{name}`, baseline `{baseline_path}/{page}/{name}_{WxH}.png` (`reporting`, `runner`).
- [x] **Piercing / iframe selectors supported** — a component `selector` may cross shadow-DOM boundaries (`>>`) or live inside an `<iframe>` (`frame_locator`); `capture_component` localizes it the same way as a plain CSS selector (`capture`).
- [x] **High config coupling is intentional** — `runner` and `capture` import 4 of `config`'s 6 types by role (orchestrator + engine work with all domain models); boundaries are by responsibility, not import count (design decision #8).
- [x] **Configurable navigation wait** — `Page.wait_until` (networkidle | domcontentloaded | load, default networkidle) forwarded to `page.goto`; live pages (polling/websockets/analytics) use domcontentloaded plus explicit `wait` actions instead of never reaching networkidle (`config`, `capture`, `playwright`).
- [x] **Deterministic capture order** — `Page.components` are kept name-sorted, so capture order never depends on filesystem ordering; a component's `setup` is self-sufficient, and `reload` (`- reload: {}`) gives point-in-time clean-page isolation without a global per-component reload tax (`config`, `runner`, `capture`, `playwright`).
- [x] **`url` ⇄ `open` exclusivity** — `Page.url: str | None`; `url = None` requires `setup` to start with an `open` action (deep-link flow), a set `url` forbids `open` as the first action — a `model_validator` enforces both, so the page is never navigated twice and never left without a start URL; `open_page` skips `goto` when `url` is None (`config`, `capture`).
- [x] **Suite-namespaced report identity** — `Outcome.suite: str` (from `Suite.name`); `testCaseId`/`historyId` = `peeksy::{suite}::{page}::{name}`, display name `{suite} / {page} / {name} [{viewport}]`, Allure suite label = real site name — the same component name on different sites never collapses in history/trends (`reporting`, `runner`).
- [x] **`mismatch_percent` is `None` for BROKEN** — no comparison happened, so the percent does not exist; a fake `0.0` would read as a perfect match in numeric filtering/aggregation. `write_results` renders the percent in statusDetails only for FAILED (`reporting`).
- [x] **Artifact paths resolve against the site folder** — `load_config` normalizes relative `baseline_path`/`results_path`/`report_path` to absolute against the site dir (absolute pass through), so generate/test behave identically from any CWD — no silent BROKEN from a different working directory (`config`).
- [x] **Masks are selector-symmetric** — `mask_selectors` are located with the same locate helper as the component selector (plain CSS, piercing `>>`, or inside an `<iframe>`), so any dynamic zone reachable from the component is maskable (`capture`, `playwright`).

## DSL self-check (Phase 6)

- [x] **Completeness** — all 19 approved types are present across the 6 CODEMANIFESTs.
- [x] **DSL correctness** — Header → `---` → Body → `---` → Footer; keys cased correctly.
- [x] **Inter-cell consistency** — every `Imports.Types`/`From` resolves to a type declared in the named cell.
- [x] **Implementation order** — leaves (config, compare, reporting) → capture → runner → cli; no cell precedes a dependency.
- [x] **No placeholders** — no TBD/TODO.
- [x] **Imports.Types usage** — every imported type is referenced in a signature or annotation of its cell.
- [x] **Imports.Usages usage** — no `Imports.Usages` declared (practices stay internal to their cells); N/A.
- [x] **Usages usage** — every declared practice (`pydantic_config`, `image_diff`, `allure`, `playwright`, `run_policy`, `typer`) is referenced in ≥1 annotation.
- [x] **Algorithms present** — routines/methods with non-trivial logic carry an `Algorithm:` block.
- [x] **No implementation details in annotations** — algorithms reference practices/types, not code.
- [x] **Backtick references resolvable** — every `` `ref` `` resolves to a signature var, a local/imported type, or a declared/imported practice.
- [x] **location restrictions** — every `location` is a bare filename with extension (models.py, loader.py, result.py, compare.py, outcome.py, writer.py, report.py, session.py, runner.py, app.py).
- [x] **No cross-imports** — import graph is acyclic (config/compare/reporting are leaves; nothing imports cli or runner).
- [x] **Embedding/mutation** — none used (no re-exports or specializations needed).
- [x] **Entity/Routine correctness** — `Viewport`, `Action`, `Component`, `Page`, `Suite`, `ComparisonResult`, `Outcome`, `CaptureSession` are Entities (have properties/methods); all `load_config`/`compare`/`write_results`/`build_report`/`run_*`/`generate`/`test`/`report`/`main` are Routines (no properties/methods).
- [x] **Base usages/annotations** — none (config absent); N/A.
- [x] **Language correctness** — PascalCase classes, snake_case functions/methods/properties; signatures use only allowed types (`str`, `int`, `float`, `bool`, `list[T]`, `T | None`); no `*args`/`**kwargs`, no untyped `list`/`dict`.