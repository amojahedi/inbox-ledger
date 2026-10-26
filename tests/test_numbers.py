"""Reconciliation: every card, chart and API field agrees with every other one (docs/definitions.md).

Runs on a freshly generated example ledger, for every month it holds.
"""
import importlib
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from inbox_ledger import config, demo

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)  # the example data ends on the 25th
TODAY = "2026-10-26"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("INBOX_LEDGER_DATA", str(tmp_path_factory.mktemp("numbers-data")))
    mp.setenv("LEDGER_TODAY", TODAY)
    st = config.open_store()
    demo_messages = demo.generate(months=6, now=NOW)
    st.add_messages(demo_messages)
    for category, limit in demo.DEMO_BUDGETS.items():
        st.set_budget(category, limit)
    st.rebuild()
    st.db.close()
    from inbox_ledger import api
    api = importlib.reload(api)
    yield TestClient(api.app)
    api.store.db.close()
    mp.undo()


# ---- definitions -------------------------------------------------------------------

def test_definitions_use_the_owners_words(client):
    d = client.get("/api/definitions").json()
    assert set(d) == {"came_in", "spent", "saved", "left", "fixed", "everyday", "settled", "hidden", "needs_review"}
    assert [d[k]["title"] for k in ("came_in", "spent", "saved", "left", "fixed", "everyday", "settled", "hidden",
                                    "needs_review")] == \
        ["Came in", "Spent", "Saved", "Left", "Fixed", "Everyday", "Settled", "Hidden", "Needs review"]
    for v in d.values():
        assert v["text"].endswith(".") and "!" not in v["text"] and len(v["text"]) < 220
