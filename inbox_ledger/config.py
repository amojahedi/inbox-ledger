"""Paths and app wiring. Everything personal lives under DATA_DIR (default ./data)."""
import os
from pathlib import Path

from .parsing import load_banks
from .store import Categories, Store

PACKAGE = Path(__file__).parent
DEFAULTS = PACKAGE / "defaults"


def data_dir() -> Path:
    return Path(os.environ.get("INBOX_LEDGER_DATA", "data")).resolve()


def open_store(db_name: str = "ledger.db") -> Store:
    d = data_dir()
    banks = load_banks(DEFAULTS / "banks", d / "banks")
    categories = Categories.load(DEFAULTS / "categories.yaml", d / "categories.yaml")
    return Store(d / db_name, banks, categories)
