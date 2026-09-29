# YAML DSL

The exhaustive, field-by-field reference of the peeksy configuration format.
Everything here is validated at load time (`peeksy.config.load_config`);
invalid files fail with a human-readable Pydantic error before any browser
launches.

Three file roles exist:

| File | Role | Named by |
|---|---|---|
| `suite.yml` | suite meta: name, artifact paths, suite-wide defaults | fixed name (or any `*.yml` passed to `--config`) |
| `pages/<page>/page.yml` | one page: URL, wait strategy, page-level setup | the folder name → `Page.name` |
| `pages/<page>/<component>.yml` | one component: selector, masks, viewports, overrides | the file stem → `Component.name` |

---

## `suite.yml`

```yaml
name: example.com
baseline_path: baselines
results_path: results
report_path: report
threshold: 0.1
tolerance: 0.5
```

| Field | Type | Range / values | Meaning |
|---|---|---|---|
| `name` | str | — | suite/site name; used as the Allure suite label and in test-case IDs |
| `baseline_path` | str | path | baseline PNG root; relative resolves against the site folder |
| `results_path` | str | path | Allure results + current/diff PNGs; relative as above |
| `report_path` | str | path | built HTML report; relative as above |
| `threshold` | float | **(0..1)** exclusive | suite-default per-pixel sensitivity forwarded to pixelmatch |
| `tolerance` | float | **(0..100]** | suite-default allowed mismatch %; PASS ⇔ `mismatch% <= tolerance` |

Validation errors: `threshold: 0`, `threshold: 1`, `threshold: 5`,
`tolerance: 0`, `tolerance: 150` all raise `ValidationError` at load time.
Unknown keys are rejected (no silently ignored typos). Run directories must
not overlap each other.

---

## `page.yml`

```yaml
url: https://example.com/
wait_until: networkidle
setup:
  - click: "#cookie-accept"
```

| Field | Type | Values | Meaning |
|---|---|---|---|
| `url` | str \| null | URL | page to open before capturing its components. `null` ⇒ **deep-link flow**: `setup` must START with an `open` action |
| `wait_until` | str | `networkidle` *(default)* \| `domcontentloaded` \| `load` | navigation wait strategy forwarded to `page.goto` |
| `setup` | list[Action] | — | page-level actions, run **once per viewport** after navigation (e.g. close a cookie banner, log in) |

Mutual exclusivity (validated in both directions):

- `url: null` requires `setup[0].kind == "open"` — the page is never left
  without a start URL
- a set `url` forbids `open` as `setup[0]` — the page is never navigated twice

---

## `<component>.yml`

```yaml
selector: "#header"
mask_selectors: [".timestamp"]
viewports:
  - {width: 1280, height: 720}
  - {width: 375, height: 667}
threshold: 0.05      # optional override
tolerance: 1.0       # optional override
setup:
  - hover: ".menu-trigger"
```

| Field | Type | Constraint | Meaning |
|---|---|---|---|
| `selector` | str | — | CSS-family selector locating the component element (see [Selectors](#selectors)) |
| `mask_selectors` | list[str] | optional | dynamic regions covered with an opaque gray overlay before the shot |
| `viewports` | list[{width, height}] | **non-empty**; width/height positive ints | one baseline/result per viewport |
| `threshold` | float \| null | (0..1) | per-pixel sensitivity override; omitted/null ⇒ inherit suite default |
| `tolerance` | float \| null | (0..100] | allowed mismatch % override; omitted/null ⇒ inherit suite default |
| `setup` | list[Action] | optional | component-level actions run before this component's shot |

A component carries **no URL** — that lives on its `Page`. Effective
threshold/tolerance resolve as `component override ?? suite default`.

### Why `viewports` must be non-empty

A component with no viewport would silently never be captured — the loader
rejects it instead. Non-positive dimensions (`width: 0`) are rejected likewise.

### mask_selectors

Masking lays an opaque gray `::after` overlay (`#808080`) over each matched
element, so the masked area is pixel-identical across runs regardless of the
dynamic content underneath, while the layout box is preserved (never
`display: none`, which would reflow neighbors). Masks are located with the
same selector syntax as the component itself and are removed right after the
shot — no leakage to the next component.

---

## Setup actions

`setup` lists appear in both `page.yml` and `<component>.yml`. Each item is a
one-key mapping: the key is the action `kind`, the value is its argument in
**short form**. The full (long) form `kind/target/value` also parses.

### Per-kind argument rules

| kind | short form | `target` | `value` | Playwright effect |
|---|---|---|---|---|
| `click` | `- click: "#cookie"` | selector | — | `locator.click()` |
| `hover` | `- hover: ".menu"` | selector | — | `locator.hover()` |
| `scroll_to` | `- scroll_to: "#main"` | selector | — | scroll element into view |
| `scroll_by` | `- scroll_by: 300` or `- scroll_by: [0, 300]` | — | pixels or `[x, y]` (whole pixels only) | `page.mouse.wheel(x, y)` |
| `fill` | `- fill: ["#search", "shoes"]` | selector | text | `locator.fill(value)` |
| `press` | `- press: "Enter"` or `- press: ["#search", "Enter"]` | optional selector | Playwright key name | press on element or page |
| `select` | `- select: ["#country", "RU"]` | selector | option | `locator.select_option(value)` |
| `wait` | see below | selector (appear) | ms or `"hidden"` | block until condition |
| `open` | `- open: "https://…"` | — | URL | `page.goto(value)` with the page's wait strategy |
| `reload` | `- reload: {}` | — | — | re-navigate current URL (clean-page isolation) |

### `wait` is overloaded by value type

```yaml
- wait: 500                              # milliseconds pause
- wait: "#loader"                        # wait for the element to appear
- wait: {selector: "#modal", hidden: true}  # wait for it to disappear
- wait: {}                               # default stabilization (load state + fonts)
```

### Rejected shapes (ValidationError)

- `- fill: "#search"` — a bare string where `[target, value]` is required
- stray keys in an action mapping (`- click: {target: "#x", foo: 1}`)
- long-form actions missing required fields
- fractional `scroll_by` pixels; non-integer ms/px strings
- unknown config keys anywhere

### Self-sufficiency rule

Actions run in list order. Components are captured in name-sorted order, so a
component's setup must not rely on side effects left by previously captured
components (open menus, scroll position, hovers) — start it with `- reload: {}`
when a clean page is needed.

---

## Selectors

`selector`, every `mask_selectors` entry, and any action `target` accept three
syntaxes:

| Syntax | Example | Meaning |
|---|---|---|
| plain CSS | `#header .title` | standard CSS |
| shadow-DOM piercing | `my-widget >> button.save` | Playwright's `>>` chaining across shadow boundaries |
| iframe hop | `iframe.ad >>> #in-frame` | the `>>>` separator (three `>`) routes through `frame_locator` |

Do **not** write `iframe.ad >> #in-frame` — the two-`>` form is shadow-DOM
piercing and matches nothing across a frame boundary.

Multi-match semantics: a frame part matching several iframes masks **every**
matching frame (every ad slot); component capture and actions use the first.

---

## Full annotated example

```yaml
# suite.yml
name: example.local
baseline_path: baselines   # → <site folder>/baselines/
results_path: results
report_path: report
threshold: 0.1             # per-pixel sensitivity (0..1)
tolerance: 0.5             # allowed mismatch % (0..100]
```

```yaml
# pages/home/page.yml
url: https://example.com/  # or null + setup starting with `open` (deep link)
wait_until: networkidle    # domcontentloaded for live pages
setup:
  - click: "#cookie-accept"
```

```yaml
# pages/home/header.yml
selector: "#header"
mask_selectors: [".timestamp"]
viewports:
  - {width: 1280, height: 720}
  - {width: 375, height: 667}
```

A runnable site with all three files lives in [`example/`](example.md) in the
repository.
