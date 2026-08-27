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
        # viewports needed by this page's components (ordered dedupe — Viewport is unhashable)
        viewports = []
        for c in page.components:
            for vp in c.viewports:
                if vp not in viewports:
                    viewports.append(vp)
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