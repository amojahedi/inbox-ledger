import pytest

from inbox_ledger.config import DEFAULTS
from inbox_ledger.parsing import load_banks
from inbox_ledger.store import Categories, Store


@pytest.fixture(scope="session")
def banks():
    return load_banks(DEFAULTS / "banks")


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "ledger.db", load_banks(DEFAULTS / "banks"),
                 Categories.load(DEFAULTS / "categories.yaml"))
