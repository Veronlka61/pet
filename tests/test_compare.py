"""Task 4 — contract + logic tests for the `peeksy.compare` cell.

Contract source: `peeksy/compare/CODEMANIFEST` (read-only). Entity
`ComparisonResult` lives at `result.py`, routine `compare` at `compare.py`,
both importable from the `peeksy.compare` facade.

Contract tests come first (TDD): facade exposure, the exact `compare` signature,
and the three record fields. Logic tests below pin the algorithm — size guard,
`<=` tolerance semantics, and diff-overlay writing — using synthetic PIL PNGs
(no browser involved).
"""

import inspect
from pathlib import Path

import pytest
from PIL import Image

import peeksy.compare as compare_facade
from peeksy.compare import ComparisonResult, compare

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


# --------------------------------------------------------------------------
# Helpers — synthetic PNG fixtures via PIL
# --------------------------------------------------------------------------


def write_solid_png(path: Path, size: tuple[int, int], rgb: tuple[int, int, int]) -> str:
    """Write a uniform-color PNG and return its path as str."""
    Image.new("RGB", size, rgb).save(path)
    return str(path)


def write_block_png(
    path: Path,
    size: tuple[int, int],
    rgb: tuple[int, int, int],
    block: tuple[int, int, int, int],
) -> str:
    """Write a uniform PNG with one opaque rectangle `block = (x0, y0, x1, y1)`."""
    image = Image.new("RGB", size, rgb)
    image.paste(BLACK, block)
    image.save(path)
    return str(path)


def png_files(directory: Path) -> list[str]:
    """Names of the PNG files currently present in `directory`."""
    return sorted(p.name for p in directory.iterdir() if p.suffix == ".png")


# --------------------------------------------------------------------------
# Contract tests — facade + signature + record fields
# --------------------------------------------------------------------------


def test_facade_exposes_compare_and_result() -> None:
    exported = set(compare_facade.__all__)
    assert {"compare", "ComparisonResult"} <= exported
    assert callable(compare_facade.compare)
    assert inspect.isclass(compare_facade.ComparisonResult)
    assert compare_facade.ComparisonResult.__module__ == "peeksy.compare.result"


def test_compare_signature_matches_contract() -> None:
    params = dict(inspect.signature(compare).parameters)
    assert list(params) == ["baseline", "current", "diff_dir", "threshold", "tolerance"]
    assert all(p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for p in params.values())
    assert params["baseline"].annotation is str
    assert params["current"].annotation is str
    assert params["diff_dir"].annotation is str
    assert params["threshold"].annotation is float
    assert params["tolerance"].annotation is float
    assert inspect.signature(compare).return_annotation is ComparisonResult


def test_comparison_result_is_immutable_record_with_three_fields() -> None:
    params = dict(inspect.signature(ComparisonResult).parameters)
    assert list(params) == ["passed", "mismatch_percent", "diff_path"]
    assert params["passed"].annotation is bool
    assert params["mismatch_percent"].annotation is float
    assert params["diff_path"].annotation == (str | None)

    result = ComparisonResult(passed=True, mismatch_percent=0.0, diff_path=None)
    assert result.passed is True
    assert result.mismatch_percent == 0.0
    assert result.diff_path is None
    with pytest.raises(AttributeError):
        result.passed = False  # type: ignore[misc]


# --------------------------------------------------------------------------
# Logic tests — the comparison algorithm on synthetic PNGs
# --------------------------------------------------------------------------


def test_compare_passes_on_identical_images(tmp_path: Path) -> None:
    baseline = write_solid_png(tmp_path / "header_1280x720.png", (100, 100), WHITE)
    current = write_solid_png(tmp_path / "header_1280x720.current.png", (100, 100), WHITE)
    diff_dir = tmp_path / "diffs"
    diff_dir.mkdir()

    result = compare(baseline, current, str(diff_dir), threshold=0.1, tolerance=0.5)

    assert result.passed is True
    assert result.mismatch_percent == 0.0
    assert result.diff_path is None
    assert png_files(diff_dir) == []


def test_compare_tolerance_boundary_semantics(tmp_path: Path) -> None:
    # 100x100 = 10_000 px; one 10x10 black block alters exactly 100 px = 1.0%.
    baseline = write_solid_png(tmp_path / "header_100x100.png", (100, 100), WHITE)
    current = write_block_png(
        tmp_path / "header_100x100.current.png", (100, 100), WHITE, (20, 20, 30, 30)
    )
    exact_diff_dir = tmp_path / "diffs-exact"
    exact_diff_dir.mkdir()
    below_diff_dir = tmp_path / "diffs-below"
    below_diff_dir.mkdir()

    # Tolerance exactly equal to the mismatch: non-strict `<=` means passed.
    exact = compare(baseline, current, str(exact_diff_dir), threshold=0.1, tolerance=1.0)
    assert exact.mismatch_percent == 1.0
    assert exact.passed is True
    assert exact.diff_path is None
    assert png_files(exact_diff_dir) == []

    # A hair below: failed, and the diff overlay is written.
    below = compare(baseline, current, str(below_diff_dir), threshold=0.1, tolerance=0.99)
    assert below.mismatch_percent == 1.0
    assert below.passed is False
    assert below.diff_path is not None
    assert Path(below.diff_path) == below_diff_dir / "header_100x100.diff.png"
    assert png_files(below_diff_dir) == ["header_100x100.diff.png"]


def test_compare_size_change_is_definite_failure(tmp_path: Path) -> None:
    baseline = write_solid_png(tmp_path / "header_1280x720.png", (1280, 720), WHITE)
    current = write_solid_png(tmp_path / "header_1280x720.current.png", (1280, 800), WHITE)
    diff_dir = tmp_path / "diffs"
    diff_dir.mkdir()

    result = compare(baseline, current, str(diff_dir), threshold=0.1, tolerance=100.0)

    assert result.passed is False
    assert result.mismatch_percent == 100.0
    assert result.diff_path is None
    assert png_files(diff_dir) == []


def test_compare_small_real_shift_writes_loadable_diff(tmp_path: Path) -> None:
    # A 2px vertical shift of a block: a small but definite layout regression.
    baseline = write_block_png(
        tmp_path / "header_200x200.png", (200, 200), WHITE, (50, 50, 150, 100)
    )
    current = write_block_png(
        tmp_path / "header_200x200.current.png", (200, 200), WHITE, (50, 52, 150, 102)
    )
    diff_dir = tmp_path / "diffs"  # deliberately absent — compare must create it

    result = compare(baseline, current, str(diff_dir), threshold=0.1, tolerance=0.5)

    assert result.passed is False
    assert 0.0 < result.mismatch_percent <= 100.0
    assert result.diff_path is not None
    diff_path = Path(result.diff_path)
    assert diff_path == diff_dir / "header_200x200.diff.png"
    assert diff_path.exists()  # diff_dir was created on demand
    with Image.open(diff_path) as diff:
        diff.load()
        assert diff.size == (200, 200)
