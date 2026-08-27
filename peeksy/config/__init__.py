"""peeksy.config — validated site configuration (variant D layout).

Cell facade: the five models (`models.py`) plus the site-folder loader
`load_config` (`loader.py`).
"""

from peeksy.config.loader import load_config
from peeksy.config.models import Action, Component, Page, Suite, Viewport

__all__ = ["Action", "Component", "Page", "Suite", "Viewport", "load_config"]
