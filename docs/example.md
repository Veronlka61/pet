# Example

A minimal, self-contained site folder ships in [`example/`](https://github.com/Veronlka61/pet/tree/main/example)
in the repository:

```
example/
├── suite.yml               # suite meta: name, artifact paths, threshold/tolerance
├── index.html              # the page under test (local file:// demo)
└── pages/
    └── home/
        ├── page.yml        # url + wait_until
        ├── header.yml      # component: 2 viewports, masked dynamic region
        └── footer.yml      # component: 1 viewport
```

The `header` component carries `mask_selectors: [".timestamp"]` — the page
fills that span with `Date.now()` on every load, and the gray overlay keeps it
out of the diff. Two viewports produce two independent test cases.

## Run it

From the repository root:

```bash
uv run peeksy generate -c example   # 3 baselines into example/baselines/
uv run peeksy test -c example       # → "all components passed", exit 0
uv run peeksy report -c example     # Allure HTML into example/report/
```

`generate`/`test`/`report` create `example/baselines/`, `example/results/`
and `example/report/` on first run — they are run artifacts, not sources.

## Introduce a regression

Edit `example/index.html` and add a 2-pixel shift to an element **inside**
the component:

```css
#header nav { transform: translateY(2px); }
```

Then:

```
$ uv run peeksy test -c example
regression or infrastructure failure detected — see the Allure report
$ echo $?
1
```

Both header viewports fail (e.g. mismatch 1.24% desktop / 3.83% mobile —
the same shifted area over a smaller crop), the footer stays PASSED, and
diff PNGs land in `example/results/home/`.

!!! note
    Shifting the component **itself** (`transform` on `#header`) is invisible:
    Playwright crops an element screenshot by the element's transformed box,
    so the box moves together with its content. Regressions must move
    something *inside* the component.

## Notes

- `pages/home/page.yml` uses an **absolute** `file://` URL pointing at
  `example/index.html` in this checkout — peeksy deliberately does not rewrite
  page URLs, so update that path after moving the folder. For live pages use
  `https://…` and prefer `wait_until: domcontentloaded` plus explicit `wait`
  actions.
