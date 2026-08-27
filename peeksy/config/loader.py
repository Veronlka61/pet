"""The peeksy site-folder loader — `load_config(path: str) -> Suite`.

Contract source: `peeksy/config/CODEMANIFEST` (read-only). Resolves the site
folder from a suite-file path or a folder path, validates the suite meta
through the `Suite` model, walks `pages/*/` (one `page.yml` plus its sibling
component `*.yml` files), and returns the validated `Suite`.

Short-form action parsing is NOT done here — the `Action` model's
`model_validator` already normalizes `- click: "#x"` style entries, so this
module only hands the raw YAML mappings to the models.
"""

import os
from pathlib import Path

import yaml
from pydantic import TypeAdapter, ValidationError

from peeksy.config.models import Component, Page, Suite

PAGE_FILE = "page.yml"
SUITE_FILE = "suite.yml"

# A page/component document must be a YAML mapping; validating the shape here
# surfaces a non-mapping file as a ValidationError (what the CLI handler
# expects) instead of a stray TypeError/ValueError.
_MAPPING = TypeAdapter(dict[str, object])


def load_config(path: str) -> Suite:
    """Discover, validate, and load a peeksy site folder.

    `path` is either a suite file (any explicitly passed `*.yml`) or a site
    folder (whose `suite.yml` is looked up). Relative `baseline_path` /
    `results_path` / `report_path` values are normalized to absolute paths
    against the site folder, so the suite behaves identically no matter which
    working directory peeksy is invoked from.
    """
    site_dir, suite_file = _resolve_site_dir(path)
    meta = _load_suite_meta(suite_file)
    pages = _load_pages(site_dir)
    return Suite(
        name=meta.name,
        pages=pages,
        baseline_path=_normalize(meta.baseline_path, site_dir),
        results_path=_normalize(meta.results_path, site_dir),
        report_path=_normalize(meta.report_path, site_dir),
        threshold=meta.threshold,
        tolerance=meta.tolerance,
    )


def _resolve_site_dir(path: str) -> tuple[Path, Path]:
    """Return `(site_dir, suite_file)` for a suite-file or folder argument.

    An explicitly passed `*.yml` IS the suite file and its parent is the site
    dir; anything else is treated as a site folder whose `suite.yml` is looked
    up inside.
    """
    candidate = Path(path).expanduser()
    if not candidate.exists():
        raise FileNotFoundError(f"config path not found: {path}")
    if candidate.suffix == ".yml":
        suite_file = candidate
    elif candidate.is_dir():
        suite_file = candidate / SUITE_FILE
    else:
        raise NotADirectoryError(
            f"config path is neither a *.yml suite file nor a site folder: {path}"
        )
    if not suite_file.is_file():
        raise FileNotFoundError(f"suite file not found: {suite_file}")
    return suite_file.parent, suite_file


def _load_suite_meta(suite_file: Path) -> Suite:
    """Read and validate the suite meta (name, paths, threshold, tolerance)."""
    raw = _read_yaml(suite_file)
    # Validate through the contract model itself (no duplicated constraints);
    # `pages` comes from the walk below, never from the suite file.
    return Suite.model_validate({**_mapping(raw, suite_file), "pages": []})


def _load_pages(site_dir: Path) -> list[Page]:
    """Walk `pages/*/` and build each `Page` with its components."""
    pages_dir = site_dir / "pages"
    if not pages_dir.is_dir():
        return []
    pages: list[Page] = []
    for page_dir in sorted(entry for entry in pages_dir.iterdir() if entry.is_dir()):
        pages.append(_load_page(page_dir))
    return pages


def _load_page(page_dir: Path) -> Page:
    """Build one `Page` from its `page.yml` plus sibling component files."""
    page_file = page_dir / PAGE_FILE
    if not page_file.is_file():
        raise FileNotFoundError(f"page file not found: {page_file}")
    raw = _mapping(_read_yaml(page_file), page_file)
    components = [_load_component(component_file) for component_file in _component_files(page_dir)]
    return Page.model_validate({**raw, "name": page_dir.name, "components": components})


def _component_files(page_dir: Path) -> list[Path]:
    """The component `*.yml` files of a page — everything but `page.yml`."""
    return sorted(
        entry
        for entry in page_dir.iterdir()
        if entry.is_file() and entry.suffix == ".yml" and entry.name != PAGE_FILE
    )


def _load_component(component_file: Path) -> Component:
    """Build one `Component`; its name comes from the filename stem."""
    raw = _mapping(_read_yaml(component_file), component_file)
    return Component.model_validate({**raw, "name": component_file.stem})


def _read_yaml(path: Path) -> object:
    """`yaml.safe_load` a file; a syntactically broken file raises YAMLError."""
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _mapping(raw: object, path: Path) -> dict[str, object]:
    """Require a YAML mapping document, reported with the offending file.

    Pydantic's `ValidationError` is not constructible by user code, so a
    non-mapping document is raised as a `ValueError` carrying the file path.
    """
    try:
        return _MAPPING.validate_python(raw)
    except ValidationError as error:
        raise ValueError(
            f"{path} must contain a YAML mapping of keys to values (got {type(raw).__name__})"
        ) from error


def _normalize(value: str, site_dir: Path) -> str:
    """Make `value` absolute against `site_dir`; absolute values pass through."""
    if os.path.isabs(value):
        return value
    return os.path.abspath(os.path.join(site_dir, value))
