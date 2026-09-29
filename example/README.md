# Example peeksy site

A minimal, self-contained site folder demonstrating the peeksy configuration
layout (variant D: site folder → page folder → component file).

```
example/
├── suite.yml               # suite meta: name, artifact paths, threshold/tolerance
├── index.html              # the page under test (local file:// demo)
└── pages/
    └── home/
        ├── page.yml        # url + wait_until (+ optional page-level setup)
        ├── header.yml      # component: 2 viewports, masked dynamic region
        └── footer.yml      # component: 1 viewport
```

## Run it

From the repository root:

```bash
uv run peeksy generate -c example   # capture 3 baselines into example/baselines/
uv run peeksy test -c example       # compare → exit 0, "all components passed"
uv run peeksy report -c example     # build the Allure HTML into example/report/
```

Then introduce a regression — e.g. add `transform: translateY(2px)` to
`#header nav` in `index.html` (a shift of an element INSIDE the component;
shifting the component itself is invisible in element screenshots) — and
`peeksy test` exits 1 with two FAILED results (one per viewport) and diff PNGs.

## Notes

- `pages/home/page.yml` uses an **absolute** `file://` URL pointing at
  `example/index.html` in this checkout. After moving/renaming the folder,
  update that path (peeksy deliberately does not rewrite page URLs).
  For live pages use `https://...` and prefer `wait_until: domcontentloaded`
  plus explicit `wait` actions (see `peeksy/config/.usages/config.md`).
- `header.yml` masks `.timestamp` — a `Date.now()` value that changes on every
  load — so the dynamic region never causes a false diff.
- `generate`/`test`/`report` create `example/baselines/`, `example/results/`,
  and `example/report/` on first run; they are run artifacts, not sources.
- Full configuration reference: `peeksy/config/.usages/config.md`.
