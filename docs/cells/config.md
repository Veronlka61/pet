# Cell: config

`peeksy.config` — validated YAML configuration model for a peeksy site
(variant D layout). Pydantic v2 models + the site-folder loader.

- **Contract:** [`peeksy/config/CODEMANIFEST`](https://github.com/Veronlka61/pet/tree/main/peeksy/config)
- **Depends on:** nothing (leaf)

## API

| Entity | Signature | Location |
|---|---|---|
| `Viewport` | `Viewport(width: int, height: int)` | `models.py` |
| `Action` | `Action(kind: str, target: str \| None, value: str \| None)` | `models.py` |
| `Component` | `Component(name, selector, mask_selectors, viewports, threshold, tolerance, setup)` | `models.py` |
| `Page` | `Page(name, url, wait_until, setup, components)` | `models.py` |
| `Suite` | `Suite(name, pages, baseline_path, results_path, report_path, threshold, tolerance)` | `models.py` |
| `load_config` | `load_config(path: str) -> Suite` | `loader.py` |

All six are re-exported from the `peeksy.config` facade (`__all__`).

## Key invariants

- `Action` is **data only** — the capture cell interprets each `kind`
  (closed set: click, hover, scroll_to, scroll_by, fill, press, select,
  wait, open, reload)
- `Page.components` is always **name-sorted** — deterministic capture order
  regardless of filesystem ordering
- `Component.name` unique within a page (namespaced by page elsewhere);
  the same name on different pages is fine
- ranges validated by the models: threshold (0..1), tolerance (0..100],
  positive viewport dimensions, non-empty `viewports`
- `url` ⇄ leading `open` mutually exclusive in **both** directions
  (model_validator)
- `load_config` normalizes relative artifact paths against the **site
  folder** — the suite is CWD-independent

See [YAML DSL](../yaml-dsl.md) for the file format these models validate.
