# Cell: runner

`peeksy.runner` — orchestrates generate/test/report over a `Suite` of pages.
No Playwright import here: it depends on `CaptureSession` only.

- **Contract:** [`peeksy/runner/CODEMANIFEST`](https://github.com/Veronlka61/pet/tree/main/peeksy/runner)
- **Depends on:** [`config`](config.md), [`capture`](capture.md), [`compare`](compare.md), [`reporting`](reporting.md)

## API

| Entity | Signature | Location |
|---|---|---|
| `run_generate` | `run_generate(suite: Suite, pages: list[str] \| None, components: list[str] \| None)` | `runner.py` |
| `run_test` | `run_test(suite, pages, components) -> int` | `runner.py` |
| `run_report` | `run_report(suite: Suite)` | `runner.py` |

## Orchestration policy

- **filters:** by page name and component name (None ⇒ all). Every filter
  value must answer to a real page/component — an unknown value raises a
  `ValueError` naming all unknowns **before** the session opens or any
  artifact is touched; a rejected run leaves prior results untouched. An
  empty selection is a no-op: no browser launch, no results reset
- **capture grouping:** by (page, viewport) — `open_page` runs once per
  pair, then each component at that viewport; viewports deduplicated in
  first-seen order over the name-sorted components (ordered list scan —
  `Viewport` is unhashable)
- **generate is fail-fast:** the first capture error closes the session and
  propagates
- **test never aborts** on capture errors — they become BROKEN outcomes;
  a missing baseline is BROKEN ("baseline not found; run `peeksy generate`"),
  never a regression
- **results hygiene:** after a successful browser launch and before the
  capture loop, each selected page's `{results_path}/{page}/` subdirectory
  is removed (stale PNGs of renamed/removed components never survive);
  before writing, prior `*-result.json`/`*-attachment` files are cleared by
  exact patterns — current `.current.png`/`.diff.png` survive
- **exit code:** 0 iff every outcome PASSED, otherwise 1

## Paths

- baseline `{baseline_path}/{page}/{name}_{WxH}.png`
- current  `{results_path}/{page}/{name}_{WxH}.current.png`
- diff     `{results_path}/{page}/{name}_{WxH}.diff.png`
