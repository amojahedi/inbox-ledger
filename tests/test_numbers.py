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


# ---- every month adds up ------------------------------------------------------------

def _months(client) -> list[dict]:
    return client.get("/api/meta").json()["months"]


def _summary(client, month: str) -> dict:
    return client.get("/api/summary", params={"month": month}).json()


def _sum(xs, key="total") -> float:
    return round(sum(x[key] for x in xs), 2)


def test_meta_has_today_and_fixed_flags(client):
    meta = client.get("/api/meta").json()
    assert meta["today"] == TODAY and meta["current"] == "2026-10"
    fixed = {c["key"] for c in meta["categories"] if c["fixed"]}
    assert fixed == {"housing", "bills", "subscriptions"}
    assert all(not c["fixed"] for c in meta["categories"] if c["custom"])


def test_spent_is_the_same_on_every_screen(client):
    months = _months(client)
    trends = client.get("/api/trends", params={"month": "2026-10"}).json()
    assert [m["month"] for m in months] == trends["months"] == ["2026-%02d" % i for i in range(5, 11)]
    for i, m in enumerate(months):
        s = _summary(client, m["month"])
        assert s["spent"] == m["spent"] == trends["spent"][i]
        assert s["spent"] == _sum(s["by_category"]) == _sum(s["by_day"]) == _sum(s["by_hour"])
        assert round(sum(v[i] for v in trends["categories"].values()), 2) == trends["spent"][i]
        assert s["received"] == m["received"] == trends["received"][i]
        assert s["moved"] == m["moved"] == trends["moved"][i]
        assert s["count"] == m["count"] == len(client.get("/api/transactions", params={"month": m["month"]}).json())


def test_each_category_page_agrees_with_the_month(client):
    for m in _months(client):
        s = _summary(client, m["month"])
        for c in s["by_category"]:
            d = client.get(f"/api/category/{c['category']}", params={"month": m["month"]}).json()
            assert d["total"] == c["total"] == _sum(d["places"])
            assert sum(p["share"] for p in d["places"]) == 100
            assert all(isinstance(p["share"], int) and p["share"] >= 0 for p in d["places"])
            assert d["trend"][-1]["total"] == c["total"]


def test_came_in_minus_spent_minus_saved_is_left(client):
    for m in _months(client):
        s = _summary(client, m["month"])
        assert s["left"] == round(s["received"] - s["spent"] - s["moved"], 2)
        assert round(s["fixed"] + s["everyday"], 2) == s["spent"]
        fixed = {"housing", "bills", "subscriptions"}
        assert s["fixed"] == _sum([c for c in s["by_category"] if c["category"] in fixed])
        assert s["everyday"] == _sum([c for c in s["by_category"] if c["category"] not in fixed])


def test_example_numbers_the_owner_chose(client):
    """Salary 30,000, saved 8,000 and rent 8,000 every month; October is exactly 13,900 and nothing passes 14,000."""
    for m in _months(client):
        s = _summary(client, m["month"])
        assert s["received"] == 30000 and s["moved"] == 8000 and s["spent"] <= 14000
        assert {c["category"]: c["total"] for c in s["by_category"]}["housing"] == 8000
    october = _summary(client, "2026-10")
    assert october["spent"] == 13900.00 and october["left"] == 8100.00


def test_most_visited_is_the_true_maximum_across_all_merchants(client):
    for m in _months(client):
        s = _summary(client, m["month"])
        rows = client.get("/api/transactions", params={"month": m["month"]}).json()
        visits: dict[str, list] = {}
        for t in rows:
            if t["spend"] > 0:
                v = visits.setdefault(t["merchant_key"], [t["merchant"], 0, 0.0])
                v[1] += 1
                v[2] += t["spend"]
        best = max(visits.values(), key=lambda v: (v[1], round(v[2], 2)))
        mv = s["most_visited"]
        assert (mv["merchant"], mv["count"], mv["total"]) == (best[0], best[1], round(best[2], 2))
        assert mv["count"] >= max(x["count"] for x in s["top_merchants"])  # never beaten by a top-8 entry
        assert set(mv) >= {"merchant", "brand", "category", "count", "total"}


def test_biggest_everyday_purchase_is_not_rent(client):
    for m in _months(client):
        s = _summary(client, m["month"])
        b = s["biggest_everyday"]
        assert b["category"] not in {"housing", "bills", "subscriptions"} and b["amount"] < 8000
        assert set(b) == {"merchant", "amount", "date", "category"} and b["date"].startswith(m["month"])
        assert s["biggest"]["merchant"] == "Landlord"  # the largest of all is still the rent


def test_server_owns_time(client):
    october, september = _summary(client, "2026-10"), _summary(client, "2026-09")
    assert october["in_progress"] is True and october["elapsed_days"] == 26
    assert september["in_progress"] is False and september["elapsed_days"] == 30
    assert september["previous_spent_to_date"] is None
    rows = client.get("/api/transactions", params={"month": "2026-09"}).json()
    to_date = round(sum(t["spend"] for t in rows if int(t["occurred_at"][8:10]) <= 26), 2)
    assert october["previous_spent_to_date"] == to_date < september["spent"]


def test_didnt_happen_moves_every_total_by_the_same_amount(client):
    rows = client.get("/api/transactions", params={"month": "2026-10", "category": "dining"}).json()
    t = next(r for r in rows if r["spend"] > 0)
    amount, day, hour = t["spend"], t["occurred_at"][:10], int(t["occurred_at"][11:13])

    def snapshot():
        s = _summary(client, "2026-10")
        d = client.get("/api/category/dining", params={"month": "2026-10"}).json()
        tr = client.get("/api/trends", params={"month": "2026-10"}).json()
        return s, d, tr

    before = snapshot()
    assert client.patch(f"/api/transactions/{t['id']}", json={"hidden": True}).status_code == 200
    try:
        after = snapshot()
        for key in ("spent", "everyday"):
            assert round(before[0][key] - after[0][key], 2) == amount
        assert round(after[0]["left"] - before[0]["left"], 2) == amount
        assert before[0]["fixed"] == after[0]["fixed"] and before[0]["count"] - after[0]["count"] == 1
        pick = lambda xs, k, v: next((x["total"] for x in xs if x[k] == v), 0.0)  # noqa: E731
        assert round(pick(before[0]["by_category"], "category", "dining") - pick(after[0]["by_category"], "category", "dining"), 2) == amount
        assert round(pick(before[0]["by_day"], "day", day) - pick(after[0]["by_day"], "day", day), 2) == amount
        assert round(pick(before[0]["by_hour"], "hour", hour) - pick(after[0]["by_hour"], "hour", hour), 2) == amount
        assert round(before[1]["total"] - after[1]["total"], 2) == amount
        assert round(_sum(before[1]["places"]) - _sum(after[1]["places"]), 2) == amount
        assert round(before[2]["spent"][-1] - after[2]["spent"][-1], 2) == amount
        assert round(before[2]["categories"]["dining"][-1] - after[2]["categories"]["dining"][-1], 2) == amount
        assert _months(client)[-1]["spent"] == after[0]["spent"]
    finally:
        client.patch(f"/api/transactions/{t['id']}", json={"hidden": False})
    assert snapshot()[0]["spent"] == before[0]["spent"]


# ---- the pieces, on small ledgers -------------------------------------------------------

def test_percents_add_up_to_100():
    from inbox_ledger.store import percents
    assert sum(percents([57.3, 8.2, 7.4, 7.1, 4.0, 4.0, 4.0, 2.0, 2.0, 2.0, 1.0, 1.0, 1.0])) == 100
    assert percents([1113.21, 900, 850, 560, 450, 250]) == [27, 22, 21, 13, 11, 6] and sum(percents([1, 1, 1])) == 100
    assert percents([50, -10, 50]) == [50, 0, 50] and percents([0, 0]) == [0, 0] and percents([]) == []
    assert percents([5]) == [100]


def test_today_can_be_set_for_demos_and_tests(monkeypatch):
    from datetime import date
    from inbox_ledger.store import today_date
    monkeypatch.setenv("LEDGER_TODAY", "2026-10-26")
    assert today_date() == date(2026, 10, 26)
    monkeypatch.setenv("LEDGER_TODAY", "not a date")
    assert today_date() == date.today()


def test_saved_is_net_of_moves_back(store):
    """8,000 to savings and 2,000 back from it: saved 6,000, and both screens agree."""
    from .helpers import salary, transfer_receipt
    store.add_messages([salary("s1"), transfer_receipt("t1", kind="Own Account", src="7710", amount="8,000.00"),
                        transfer_receipt("t2", kind="Own Account", src="3390", amount="2,000.00",
                                         date="2026-10-20T10:00:00Z")])
    store.rebuild()
    s = store.summary("2026-10", today=__import__("datetime").date(2026, 10, 26))
    assert (s["moved"], s["left"], s["count"]) == (6000.0, 12500.0, 1)  # the salary is the one transaction
    assert store.trends("2026-10")["moved"] == [6000.0] and store.months()[0]["moved"] == 6000.0
    moves = {t["account"]: t["extra"].get("moved_back") for t in store.transactions(internal="only")}
    assert moves == {"7710": None, "3390": True}


def test_every_move_counts_as_saved_without_a_main_account(store):
    from .helpers import transfer_receipt
    store.add_messages([transfer_receipt("t1", kind="Own Account", src="7710", amount="100.00"),
                        transfer_receipt("t2", kind="Own Account", src="3390", amount="40.00")])
    store.rebuild()
    assert store.summary("2026-10")["moved"] == 140.0


def test_months_and_summary_count_the_same_rows(store):
    from .helpers import card, salary, transfer_receipt
    store.add_messages([salary("s1"), card("c1", "CAREEM FOOD DUBAI AE"), card("c2", "ARABICA DUBAI AE"),
                        transfer_receipt("t1", kind="Own Account", src="7710", amount="500.00")])
    store.rebuild()
    assert store.months()[0]["count"] == store.summary("2026-10")["count"] == 3 == len(store.transactions(internal="hide"))
