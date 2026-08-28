"""`build_report` — Stage 2: build the browsable Allure HTML report.

Shells out to the external `allure` CLI (Java-based). The CLI is an accepted
optional dependency of peeksy, so a missing binary raises a human-readable
error with install instructions here — never a raw `FileNotFoundError` out of
`subprocess` that a user cannot act on.
"""

import shutil
import subprocess

# The argv is pinned by the design: results dir positional FIRST, then
# `--clean`, then `-o <report_dir>`. This overrides the example snippet in
# `.goga/usages/cooks/allure.md`, which shows the results dir last.
_ALLURE_MISSING = (
    "the 'allure' CLI was not found on PATH — it is required to build the HTML report. "
    "Install it with `brew install allure` or via sdkman (`sdk install allure`); "
    "it is Java-based, so a JDK is required too."
)
# Every other external boundary in peeksy carries an explicit bound (the
# capture cell's ACTION_TIMEOUT_MS). Without one here, a wedged JVM blocks
# `peeksy report` forever with its output swallowed by capture_output.
_ALLURE_TIMEOUT_S = 600


def build_report(results_dir: str, report_dir: str) -> None:
    """Generate the Allure HTML report from `results_dir` into `report_dir`."""
    if shutil.which("allure") is None:
        raise RuntimeError(_ALLURE_MISSING)

    try:
        subprocess.run(
            ["allure", "generate", results_dir, "--clean", "-o", report_dir],
            check=True,
            capture_output=True,
            timeout=_ALLURE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"the 'allure' CLI did not finish within {_ALLURE_TIMEOUT_S}s — "
            "it may be hung; re-run `peeksy report` or investigate the JVM"
        ) from error
