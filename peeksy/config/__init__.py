"""peeksy.config — validated site configuration (variant D layout).

Cell facade. The models live in `models.py`; `load_config` (the site-folder
loader) lands in `loader.py` with Task 3.
"""

from peeksy.config.models import Action, Component, Page, Suite, Viewport

__all__ = ["Action", "Component", "Page", "Suite", "Viewport"]
