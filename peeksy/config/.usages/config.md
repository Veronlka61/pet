# config — Loading and Using the peeksy Site Configuration

## Domain

How to load and consume the validated peeksy site configuration (variant D: site folder →
page folder → component file). Target audience: the `runner` and `cli` cells that need a `Suite`.

## Load a suite

```python
from peeksy.config import load_config

suite = load_config("peeksy.yml")  # the suite file directly (any *.yml name)
suite = load_config("sites/example.com")  # or a site folder
suite = load_config("sites/example.com/suite.yml")  # or the suite.yml inside a folder
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