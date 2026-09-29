# CLI Usage

```
peeksy generate|test [--config PATH] [--page NAME]... [--component NAME]...
peeksy report [--config PATH]
```

## Options

- `--config` / `-c` — suite file or site folder. Default `./peeksy.yml`;
  a folder argument looks up its `suite.yml`. Relative artifact paths inside
  the suite resolve against the site folder, so the CLI behaves identically
  from any working directory.
- `--page`, `--component` — repeatable name filters, combined as an AND.
  Omit them to process everything.

## Unknown filter values are errors

Any `--page`/`--component` value no page or component answers to fails the run
before a browser launches (exit 1, prior results untouched):

```
$ peeksy test --page hom2        # a typo in "home"
error: filter matched nothing: unknown page 'hom2' (known pages: ['home'])
```

A typo must never become a green run that silently compares fewer components.
An empty suite (no pages at all) is a genuine no-op and passes through.

## Exit codes

`test` exits 0 only when every selected component PASSED:

- **0** — all components passed
- **1** — any FAILED (visual regression) or BROKEN (infrastructure: missing
  baseline, selector not found, unreadable image, failed page setup)

`test` never aborts on capture errors — they become BROKEN outcomes and the
run continues. `generate` is fail-fast: the first capture error stops the run
(re-run with `--page`/`--component` to resume).

`test` prints a one-line summary:

- `all components passed`
- `regression or infrastructure failure detected — see the Allure report`

## report

`peeksy report` builds the Allure HTML from the results directory. It requires
the external `allure` CLI on PATH; when it is missing, peeksy prints a clear
install message (no traceback) and exits 1.
