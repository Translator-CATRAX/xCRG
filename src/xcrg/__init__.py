"""Reusable xCRG package."""

from .config import XCRGConfig
from .runner import async_run_xcrg, is_xcrg_mvp2_query, run_xcrg

__all__ = [
    "XCRGConfig",
    "async_run_xcrg",
    "is_xcrg_mvp2_query",
    "run_xcrg",
]

__version__ = "0.1.0"
