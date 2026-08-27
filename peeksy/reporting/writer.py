"""`write_results` — Stage 1: Allure result JSON + attachments for a set of outcomes.

One `<uuid>-result.json` per `Outcome`. `testCaseId`/`historyId` are
suite+page-namespaced AND viewport-suffixed, so the same component name on
different pages, different sites, or at different viewports never collapses in
Allure history/trends. Does NOT clear prior artifacts — that is the runner's
responsibility; this routine only writes what it is given.
"""

import json
import shutil
import uuid
from pathlib import Path

from allure_commons.model2 import Attachment, Label, Status, StatusDetails, TestResult

from peeksy.reporting.outcome import Outcome

# Outcome.status (uppercase contract form) -> Allure Status.
_STATUS_MAP: dict[str, str] = {
    "PASSED": Status.PASSED,
    "FAILED": Status.FAILED,
    "BROKEN": Status.BROKEN,
}


def write_results(outcomes: list[Outcome], results_dir: str) -> None:
    """Write one Allure result JSON per outcome, copying PNGs as attachments."""
    target = Path(results_dir)
    target.mkdir(parents=True, exist_ok=True)

    for outcome in outcomes:
        case_id = f"peeksy::{outcome.suite}::{outcome.page}::{outcome.name}[{outcome.viewport}]"

        attachments = []
        for role, path in (
            ("baseline", outcome.baseline_path),
            ("current", outcome.current_path),
            ("diff", outcome.diff_path),
        ):
            if path is None:  # BROKEN outcomes omit the missing image cleanly
                continue
            attachments.append(
                Attachment(
                    source=_copy_attachment(Path(path), target),
                    name=role,
                    type="image/png",
                )
            )

        result = TestResult(
            uuid=str(uuid.uuid4()),
            name=f"{outcome.suite} / {outcome.page} / {outcome.name} [{outcome.viewport}]",
            historyId=case_id,
            testCaseId=case_id,
            status=_STATUS_MAP[outcome.status],
            statusDetails=_status_details(outcome),
            labels=[Label(name="suite", value=outcome.suite)],
            attachments=attachments,
        )
        (target / f"{result.uuid}-result.json").write_text(
            json.dumps(result.to_dict() if hasattr(result, "to_dict") else _as_dict(result)),
            encoding="utf-8",
        )


def _copy_attachment(source: Path, results_dir: Path) -> str:
    """Copy a PNG into `results_dir` as `<new-uuid>-attachment`; return that filename."""
    destination = f"{uuid.uuid4()}-attachment"
    shutil.copy2(source, results_dir / destination)
    return destination


def _status_details(outcome: Outcome) -> StatusDetails:
    """Mismatch % when FAILED, error when BROKEN; None for a clean pass."""
    if outcome.status == "FAILED":
        return StatusDetails(message=f"mismatch: {outcome.mismatch_percent:.2f}%")
    if outcome.status == "BROKEN":
        return StatusDetails(message=outcome.error)
    return None


def _as_dict(item: object) -> dict:
    """Serialize an allure-commons attrs record, dropping None/empty fields."""
    from attr import asdict

    return asdict(item, filter=lambda _, value: value or value is False)
