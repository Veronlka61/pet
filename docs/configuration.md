# Configuration

peeksy is configured as a **site folder** (layout "variant D"):
site folder → page folder → component file.

```
my-site/                     # the site folder
├── suite.yml                # suite meta: name, artifact paths, defaults
└── pages/
    └── home/                # a page folder = page name
        ├── page.yml         # url, wait_until, page-level setup
        ├── header.yml       # a component file = component name
        └── footer.yml
```

Any explicitly passed `*.yml` suite file works too — its parent directory
becomes the site folder. `--config/-c` defaults to `./peeksy.yml` in the
project root (one repository = one site).

See [YAML DSL](yaml-dsl.md) for the exhaustive field-by-field reference.

## Names come from the filesystem

- `Component.name` — the component file's stem (`header.yml` → `header`)
- `Page.name` — the page folder's name (`pages/home/` → `home`)

Component names must be unique **within a page** — baselines and Allure IDs
are namespaced by page. The same name on different pages is fine.

## Path resolution

Relative `baseline_path`/`results_path`/`report_path` in `suite.yml` resolve
against the **site folder**, not the current working directory:

```
baseline_path: baselines   # next to my-site/suite.yml → my-site/baselines/
```

Absolute paths pass through unchanged. Artifacts land page-namespaced:

- baselines: `{baseline_path}/{page}/{name}_{WxH}.png`
- current:   `{results_path}/{page}/{name}_{WxH}.current.png`
- diffs:     `{results_path}/{page}/{name}_{WxH}.diff.png`

## Two thresholds — do not conflate them

- `threshold` **(0..1)** — per-pixel color sensitivity forwarded to pixelmatch
  (lower = stricter per pixel)
- `tolerance` **(0..100]** — allowed mismatch **percent** that decides the
  verdict: a component PASSES when `mismatch% <= tolerance`

Both accept a per-component override; `null`/omitted means "inherit the suite
default" (`component override ?? suite default`).

## Page discovery rules

- every page folder must contain `page.yml` — a folder with other YAML but no
  `page.yml` fails the load loudly
- a page folder must hold at least one component `*.yml` besides `page.yml`
  (a common cause of failure is the `.yaml` extension, which is **not** picked up)
- subfolders of `pages/` with no YAML at all (`__pycache__/`, `node_modules/`)
  are skipped as artifact directories, not errors

## Navigation strategy

`wait_until` selects how `page.goto` waits:

- `networkidle` (default) — wait for the network to drain; best for static pages
- `domcontentloaded` / `load` — for live pages (long-polling, websockets,
  constant analytics) that never reach `networkidle`; pair with explicit
  `- wait: "#content"` actions in setup

When `url` is omitted (`url: null`), the page runs a **deep-link flow**: its
`setup` must start with an `open` action that performs the navigation. A set
`url` forbids `open` as the first setup action — the page is never navigated
twice and never left without a start URL (validated in both directions).

## Determinism model

- components are captured in **name-sorted** order within a page — deterministic
  regardless of filesystem ordering
- a component's `setup` must be self-sufficient: it must not rely on side
  effects of previously captured components; start it with `- reload: {}` when
  the component needs a clean page
- dynamic regions (timestamps, ads, counters) are covered with an opaque gray
  overlay via `mask_selectors` — see [YAML DSL](yaml-dsl.md#mask_selectors)
