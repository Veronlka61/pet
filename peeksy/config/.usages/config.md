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
- `component.setup` runs before that component's shot.
- Per-component `threshold`/`tolerance` override the suite defaults; `None` means inherit.

## Setup actions (short form)

`page.setup` and `component.setup` are lists of actions written in a short YAML form:

```yaml
# page.yml — page-level setup runs once per viewport
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
```

- A single string is the `target` for click/hover/scroll_to, or the `value` for press/scroll_by/open.
- A list is `[target, value]` for fill/select (and optionally press).
- `open` navigates the page to its `value` URL (target is unused); useful for redirects or
  deep-linking to a state mid-setup.
- `wait` is overloaded by value type (see examples).

## Naming and uniqueness

- `Component.name` comes from its filename; `Page.name` from its folder name.
- Component names must be unique **within a page** (they are namespaced by page in the
  baseline path and `testCaseId`). The same name on different pages is fine.

## Paths

- `suite.baseline_path` — baseline PNGs, organized as `{baseline_path}/{page}/{name}_{WxH}.png`
- `suite.results_path` — Allure results + current/diff PNGs
- `suite.report_path` — built HTML report