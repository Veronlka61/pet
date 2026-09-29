# Cell: capture

`peeksy.capture` — deterministic element-level screenshots via Playwright,
including execution of page/component setup actions. **Playwright never
leaks outside this cell** (enforced by a test).

- **Contract:** [`peeksy/capture/CODEMANIFEST`](https://github.com/Veronlka61/pet/tree/main/peeksy/capture)
- **Depends on:** [`config`](config.md) — `Component`, `Viewport`, `Page`, `Action`

## API

| Entity | Signature | Location |
|---|---|---|
| `CaptureSession` | methods below | `session.py` |

| Method | Signature |
|---|---|
| `open` | `open()` — headless Chromium, one context `device_scale_factor=1`, one page |
| `open_page` | `open_page(page: Page, viewport: Viewport)` |
| `capture_component` | `capture_component(component: Component, out_path: str) -> str` |
| `close` | `close()` — idempotent teardown |

## Two-level setup

- `open_page` (once per page+viewport): set viewport → `goto` (or let the
  deep-link `open` action navigate) → inject determinism CSS (animations,
  transitions, caret off) + `document.fonts.ready` → run `page.setup`
- `capture_component` (per component): run `component.setup` → **re-apply**
  determinism (an `open`/`reload` in setup navigates away and drops the
  style tag) → mask → wait visible → screenshot → unmask

## Determinism rules

- one browser + one context (`device_scale_factor=1` — a Retina DPR would
  double every diff) reused across the whole run
- masking: opaque gray `::after` overlay (`#808080`, z-index 99999) —
  pixel-identical masks regardless of underlying content, layout box
  preserved (never `display: none`); the mask class is removed after the
  shot so nothing leaks to the next component
- captures are **idempotent**: the same component on the same open page
  produces pixelmatch-clean images
- selectors: plain CSS, shadow-DOM piercing (`a >> b`), or iframe content
  (`frame >>> inner`) — one `locate` helper for the component selector and
  every mask selector; multi-frame masks reach **every** matching frame
- Playwright errors (`Error`/`TimeoutError`) propagate to the runner,
  which turns them into BROKEN outcomes
