"""Versioned resume parser adapters.

The adapters parse text that an HR user has legally exported or uploaded.  They do
not connect to, authenticate with, or scrape any job board.
"""

from app.parsers.registry import AdapterOutput, select_adapter

__all__ = ["AdapterOutput", "select_adapter"]
