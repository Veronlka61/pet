"""Task 5 — contract + logic tests for `peeksy.reporting` stage 1.

Contract source: `peeksy/reporting/CODEMANIFEST` (read-only). Entity `Outcome`
lives at `outcome.py`, routine `write_results` at `writer.py`, both importable
from the `peeksy.reporting` facade.

Contract tests come first (TDD): facade exposure, the `write_results` signature
returning None, and the ten `Outcome` fields. Logic tests below pin the Allure
conventions — stable testCaseId/historyId per (suite, page, component,
viewport), the display name, the suite label, attachment copying for non-None
paths only, and statusDetails semantics per status.
"""

import inspect
import json
from pathlib import Path

from PIL import Image

import peeksy.reporting as reporting_facade
from peeksy.reporting import Outcome, write_results

WHITE = (255, 255, 255)


# --------------------------------------------------------------------------
# Helpers — tiny PIL PNGs and Allure result reading
# --------------------------------------------------------------------------


def write_png(path: Path, rgb: tuple[int, int, int] = WHITE) -> str:
    """Write a small solid PNG and return its path as str."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), rgb).save(path)
    return str(path)


def read_results(results_dir: Path) -> list[dict]:
    """Parse every `*-result.json` in `results_dir` into a list of dicts."""
    files = sorted(results_dir.glob("*-result.json"))
    assert files, f"no *-result.json written into {results_dir}"
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def attachment_files(results_dir: Path) -> list[str]:
    """Names of the copied `*-attachment` files currently in `results_dir`."""
    return sorted(p.name for p in results_dir.glob("*-attachment"))


def make_outcome(**overrides: object) -> Outcome:
    """A PASSED `Outcome` with baseline+current, overridable field by field."""
    defaults: dict[str, object] = {
        "suite": "demo-site",
        "page": "home",
        "name": "header",
        "viewport": "1280x720",
        "status": "PASSED",
        "mismatch_percent": 0.0,
        "baseline_path": None,
        "current_path": None,
        "diff_path": None,
        "error": None,
    }
    defaults.update(overrides)
    return Outcome(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Contract tests — facade + signature + record fields
# --------------------------------------------------------------------------


def test_facade_exposes_outcome_and_write_results() -> None:
    exported = set(reporting_facade.__all__)
    assert {"Outcome", "write_results"} <= exported
    assert inspect.isclass(reporting_facade.Outcome)
    assert callable(reporting_facade.write_results)
    assert reporting_facade.Outcome.__module__ == "peeksy.reporting.outcome"
    assert reporting_facade.write_results.__module__ == "peeksy.reporting.writer"


def test_write_results_signature_matches_contract() -> None:
    signature = inspect.signature(write_results)
    params = dict(signature.parameters)
    assert list(params) == ["outcomes", "results_dir"]
    assert all(p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for p in params.values())
    assert params["outcomes"].annotation == (list[Outcome])
    assert params["results_dir"].annotation is str
    assert signature.return_annotation is None


def test_outcome_is_immutable_record_with_ten_fields() -> None:
    params = dict(inspect.signature(Outcome).parameters)
    assert list(params) == [
        "suite",
        "page",
        "name",
        "viewport",
        "status",
        "mismatch_percent",
        "baseline_path",
        "current_path",
        "diff_path",
        "error",
    ]
    annotations = Outcome.__annotations__
    assert annotations["suite"] is str
    assert annotations["page"] is str
    assert annotations["name"] is str
    assert annotations["viewport"] is str
    assert annotations["status"] is str
    assert annotations["mismatch_percent"] == (float | None)
    assert annotations["baseline_path"] == (str | None)
    assert annotations["current_path"] == (str | None)
    assert annotations["diff_path"] == (str | None)
    assert annotations["error"] == (str | None)

    outcome = make_outcome()
    assert outcome.suite == "demo-site"
    assert outcome.status == "PASSED"
    assert outcome.mismatch_percent == 0.0
    assert outcome.error is None
    try:
        outcome.status = "FAILED"  # type: ignore[misc]
    except AttributeError:
        pass
    else:  # pragma: no cover - the record must be immutable
        raise AssertionError("Outcome must be an immutable record")


# --------------------------------------------------------------------------
# Logic tests — PASSED / FAILED / BROKEN and the identity conventions
# --------------------------------------------------------------------------


def test_passed_outcome_writes_one_result_with_two_attachments(tmp_path: Path) -> None:
    results_dir = tmp_path / "allure-results"
    baseline = write_png(tmp_path / "baseline" / "header_1280x720.png")
    current = write_png(tmp_path / "current" / "header_1280x720.current.png")

    write_results([make_outcome(baseline_path=baseline, current_path=current)], str(results_dir))

    (result,) = read_results(results_dir)
    assert result["name"] == "demo-site / home / header [1280x720]"
    assert result["historyId"] == "peeksy::demo-site::home::header[1280x720]"
    assert result["testCaseId"] == "peeksy::demo-site::home::header[1280x720]"
    assert result["status"] == "passed"
    assert {"name": "suite", "value": "demo-site"} in result["labels"]

    sources = [a["source"] for a in result["attachments"]]
    names = [a["name"] for a in result["attachments"]]
    assert names == ["baseline", "current"]
    assert len(attachment_files(results_dir)) == 2
    assert set(sources) == set(attachment_files(results_dir))
    for source in sources:
        assert source.endswith("-attachment")
    # A pass carries no verdict message — there is nothing to explain.
    assert "statusDetails" not in result


def test_failed_outcome_attaches_diff_and_reports_mismatch(tmp_path: Path) -> None:
    results_dir = tmp_path / "allure-results"
    baseline = write_png(tmp_path / "b.png")
    current = write_png(tmp_path / "c.png")
    diff = write_png(tmp_path / "d.png")

    write_results(
        [
            make_outcome(
                status="FAILED",
                mismatch_percent=2.5,
                baseline_path=baseline,
                current_path=current,
                diff_path=diff,
            )
        ],
        str(results_dir),
    )

    (result,) = read_results(results_dir)
    assert result["status"] == "failed"
    assert [a["name"] for a in result["attachments"]] == ["baseline", "current", "diff"]
    assert len(attachment_files(results_dir)) == 3
    assert "2.5" in result["statusDetails"]["message"]
    assert "mismatch" in result["statusDetails"]["message"].lower()


def test_broken_outcome_omits_missing_attachments_and_never_renders_mismatch(
    tmp_path: Path,
) -> None:
    results_dir = tmp_path / "allure-results"
    baseline = write_png(tmp_path / "b.png")

    write_results(
        [
            make_outcome(
                status="BROKEN",
                mismatch_percent=None,
                baseline_path=baseline,
                current_path=None,
                error="page setup failed: net::ERR_CONNECTION_REFUSED",
            )
        ],
        str(results_dir),
    )

    (result,) = read_results(results_dir)
    assert result["status"] == "broken"
    names = [a["name"] for a in result["attachments"]]
    assert names == ["baseline"]  # current omitted — no fake placeholder
    assert len(attachment_files(results_dir)) == 1
    assert result["statusDetails"]["message"] == "page setup failed: net::ERR_CONNECTION_REFUSED"
    # mismatch_percent is None for BROKEN — never a fake 0.0 anywhere in the JSON.
    assert "mismatch" not in result["statusDetails"]["message"].lower()
    assert "0.0" not in result["statusDetails"]["message"]


def test_write_results_creates_absent_results_dir(tmp_path: Path) -> None:
    results_dir = tmp_path / "nested" / "allure-results"  # deliberately absent
    assert not results_dir.exists()

    write_results([make_outcome()], str(results_dir))

    assert results_dir.is_dir()
    assert len(list(results_dir.glob("*-result.json"))) == 1


def test_viewports_get_distinct_history_ids(tmp_path: Path) -> None:
    results_dir = tmp_path / "allure-results"
    outcomes = [
        make_outcome(viewport="1280x720"),
        make_outcome(viewport="375x667"),
    ]

    write_results(outcomes, str(results_dir))

    # Result filenames are uuid-random, so order by the display name instead.
    wide, narrow = sorted(read_results(results_dir), key=lambda r: r["name"])
    assert wide["historyId"] == "peeksy::demo-site::home::header[1280x720]"
    assert narrow["historyId"] == "peeksy::demo-site::home::header[375x667]"
    assert wide["historyId"] != narrow["historyId"]
    assert wide["testCaseId"] != narrow["testCaseId"]
    assert wide["name"] != narrow["name"]
