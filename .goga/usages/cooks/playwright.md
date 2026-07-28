# Playwright — Capture Patterns for Visual Regression

## Domain

Capturing deterministic, component-level screenshots of web pages with
**Playwright (Python, sync API)**. Target audience: the cell that opens a page,
locates a UI component by selector, and produces a baseline/current PNG.

This file covers *how to use Playwright* for visual-regression capture. It does
not describe the cell contract.

---

## Why Playwright

- `locator.screenshot()` returns the **element's bounding box only** — true
  component screenshots, not full-page crops.
- Built-in auto-wait + `wait_until` modes make captures reproducible.
- Chromium is installed and managed via `playwright install chromium`; no
  separate driver binary.

---

## Setup

```bash
uv add playwright
uv run playwright install chromium      # downloads the browser once
```

---

## Lifecycle — one browser, one context, pages reused

A capture run opens **one browser** and **one context** for the whole suite,
then reuses a single `page` across components. Spinning up a browser per
component is an order of magnitude slower and unnecessary.

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        device_scale_factor=1,   # fixed DPR -> stable pixel output
    )
    page = context.new_page()
    try:
        for component in suite:
            png = capture_component(page, component)
            # ...save baseline or hand to comparator
    finally:
        context.close()
        browser.close()
```

`device_scale_factor=1` is mandatory for reproducible pixel diffs — a Retina
context (DPR 2) renders the same component at double resolution and every diff
explodes.

---

## Capture routine

```python
def capture_component(page, component) -> bytes:
    # 1. Navigate and settle the network
    page.goto(component.url, wait_until="networkidle")

    # 2. Kill non-determinism: animations, caret, hover transitions
    page.add_style_tag(content="*, *::before, *::after {"
                               "animation: none !important;"
                               "transition: none !important;"
                               "caret-color: transparent !important;}")

    # 3. Wait for fonts so glyphs are laid out before the shot
    page.evaluate("document.fonts.ready")

    # 4. Locate the component and capture its bounding box
    locator = page.locator(component.selector).first
    locator.wait_for(state="visible")
    return locator.screenshot(type="png")
```

### Rules baked into the routine

- **`wait_until="networkidle"`** — wait for in-flight requests to drain so
  lazy-loaded content is present. For pages with long-polling/websockets use
  `"domcontentloaded"` plus an explicit `locator.wait_for()`.
- **Disable animations/transitions** — they are time-dependent and make every
  run flaky.
- **`document.fonts.ready`** — font swap after screenshot shifts glyphs.
- **`wait_for(state="visible")`** — the element must occupy layout space.

---

## Masking dynamic regions

Timestamps, ads, avatars, and counters change between runs and produce false
positives. Mask them: hide or freeze them before the shot.

```python
# Hide every element matching a "mask" selector list from the config
for mask_selector in component.mask_selectors:
    page.locator(mask_selector).evaluate(
        "el => el.style.visibility = 'hidden'"
    )
```

For full-page captures Playwright offers `mask=[...]` on `page.screenshot()`,
but element screenshots (`locator.screenshot()`) do not accept `mask` — hide
regions via style as shown above.

---

## Setup actions

Before the shot, a page or component may need interactions — close a cookie banner,
hover a menu, fill a field, switch a tab. These come from the config as a list of
`Action(kind, target, value)` and run in order via Playwright.

| kind | Playwright call | target / value |
|---|---|---|
| `click` | `locator(target).click()` | target = selector |
| `hover` | `locator(target).hover()` | target = selector |
| `scroll_to` | `locator(target).scroll_into_view_if_needed()` | target = selector |
| `scroll_by` | `page.mouse.wheel(x, y)` | value = px (y), or `[x, y]` |
| `fill` | `locator(target).fill(value)` | target = selector, value = text |
| `press` | `locator(target).press(value)` / `page.keyboard.press(value)` | value = key; target optional |
| `select` | `locator(target).select_option(value)` | target = selector, value = option |
| `wait` | `wait_for_selector` / `wait_for_timeout` / networkidle | target = selector (appear); `hidden` (disappear); value = ms; nothing = default |
| `open` | `page.goto(value, wait_until="networkidle")` | value = URL; target = None |

```python
def run_actions(page, actions):
    for action in actions:                      # run in list order
        if action.kind == "click":
            page.locator(action.target).click()
        elif action.kind == "hover":
            page.locator(action.target).hover()
        elif action.kind == "scroll_to":
            page.locator(action.target).scroll_into_view_if_needed()
        elif action.kind == "scroll_by":
            x, y = parse_xy(action.value)       # "300" -> (0, 300); [0, 300] -> (0, 300)
            page.mouse.wheel(x, y)
        elif action.kind == "fill":
            page.locator(action.target).fill(action.value)
        elif action.kind == "press":
            (page.locator(action.target) if action.target else page.keyboard).press(action.value)
        elif action.kind == "select":
            page.locator(action.target).select_option(action.value)
        elif action.kind == "wait":
            run_wait(page, action)              # see wait rules below
        elif action.kind == "open":
            page.goto(action.value, wait_until="networkidle")  # navigate to action.value URL
```

### `wait` rules

- `wait` with a `target` selector → `page.wait_for_selector(target, state="visible")`.
- `wait` with a `target` and `value == "hidden"` → `wait_for_selector(target, state="hidden")`.
- `wait` with a numeric `value` (ms) → `page.wait_for_timeout(int(value))`.
- `wait` with neither → default stabilization: `page.wait_for_load_state("networkidle")`
  + `page.evaluate("document.fonts.ready")` + a short settle pause. Use it between steps
  when animations or lazy content need to settle.

### Rules baked in

- Actions run **in list order**; a failing action (selector missing, timeout) bubbles up as a
  capture error → the runner records the component as `BROKEN`, not as a visual diff.
- Keep setups deterministic: avoid actions that depend on wall-clock time or external state.

---

## Viewports

Each viewport in the config becomes a separate capture. Recreate the context
per viewport (or `page.set_viewport_size`) so layout reflows fully before the
shot:

```python
for viewport in component.viewports:
    page.set_viewport_size({"width": viewport.width, "height": viewport.height})
    # re-run settle + mask steps, then capture
```

---

## Reusability contract for the capture cell

- Input: a resolved component spec (`url`, `selector`, `mask_selectors`,
  `viewports`) plus a shared `page`.
- Output: PNG bytes (or a path) per `(component, viewport)`.
- Must be idempotent: two consecutive captures of the same component under the
  same viewport produce byte-identical (or pixelmatch-clean) images.

---

## Failure modes to expect

- Selector matches nothing → `locator.wait_for` throws `TimeoutError`. Surface
  it as a capture error, not a diff failure.
- Element is inside a shadow DOM → use a piercing selector or
  `locator.frame_locator(...)`.
- Page never reaches `networkidle` → fall back to `"domcontentloaded"` + an
  explicit wait.
