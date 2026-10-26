"""The month in plain words: insights.py and GET /api/insights."""
import importlib
import re
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from inbox_ledger import config, demo, insights
from inbox_ledger.config import DEFAULTS
from inbox_ledger.parsing import load_banks
from inbox_ledger.paylater import load_providers
from inbox_ledger.store import Categories, Store

NOW = datetime(2026, 10, 26, 8, 0)  # the example data then runs 1 July – 25 October
MONTH, PREV = "2026-10", "2026-09"


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    st = Store(tmp_path_factory.mktemp("insights") / "ledger.db", load_banks(DEFAULTS / "banks"),
               Categories.load(DEFAULTS / "categories.yaml"), load_providers(DEFAULTS / "paylater"))
    st.add_messages(demo.generate(months=4, now=NOW))
    for key, limit in demo.DEMO_BUDGETS.items():
        st.set_budget(key, limit)
    st.rebuild()
    yield st
    st.db.close()


def spend(st, where, *args):
    return round(st.db.execute(f"SELECT coalesce(sum(spend),0) FROM transactions WHERE counted=1 AND {where}", args).fetchone()[0], 2)


def test_fixed_and_everyday_add_up(seeded):
    d = insights.build(seeded, MONTH, demo=True, today=NOW.date())
    s = seeded.summary(MONTH)
    assert set(d["fixed_keys"]) == {"housing", "bills", "subscriptions"}
    assert d["fixed"] + d["everyday"] == pytest.approx(s["spent"], abs=0.01)
    assert d["fixed"] == pytest.approx(sum(c["total"] for c in s["by_category"] if c["category"] in d["fixed_keys"]), abs=0.01)
    # The per-day and per-hour splits add up to the same two numbers.
    assert sum(x["everyday"] for x in d["by_day"]) == pytest.approx(d["everyday"], abs=0.05)
    assert sum(x["total"] for x in d["by_day"]) == pytest.approx(s["spent"], abs=0.05)
    assert sum(x["everyday"] for x in d["by_hour"]) <= sum(x["total"] for x in d["by_hour"]) + 0.01
    assert [x["day"] for x in d["by_day"]] == [x["day"] for x in s["by_day"]]


def test_example_month_reads_as_finished(seeded):
    d = insights.build(seeded, MONTH, demo=True, today=NOW.date())
    assert d["in_progress"] is False and d["elapsed_days"] == 31 and d["days"] == 31
    assert d["previous_spent_to_date"] is None
    assert d["review"] == []  # example data gets no month in review


def test_example_month_has_at_least_three_true_lines(seeded):
    d = insights.build(seeded, MONTH, demo=True, today=NOW.date())
    lines = d["lines"]
    assert 3 <= len(lines) <= insights.MAX_LINES
    kinds = [l["kind"] for l in lines]
    assert kinds == sorted(kinds, key=["change", "budget", "missing", "merchant", "paylater"].index)  # ranked
    for l in lines:
        assert "!" not in l["text"]
        for i in re.findall(r"\{(\d+)\}", l["text"]):
            assert int(i) < len(l["amounts"])
        if "{category}" in l["text"]:
            assert l["category"] in seeded.categories.by_key
        assert l["to"] in ("category", "activity")
    # Pay later is one line, never a box, and its numbers are the summary's.
    pl = next(l for l in lines if l["kind"] == "paylater")
    s = seeded.summary(MONTH)
    assert pl["amounts"] == [s["pay_later"][0]["paid"], s["pay_later"][0]["owed"]] and pl["via"] == "Tabby"
    # A category line compares this month with the average of the three before it.
    for l in lines:
        if l["kind"] == "change":
            now, avg = l["amounts"]
            assert now == pytest.approx(spend(seeded, "month=? AND category=?", MONTH, l["category"]), abs=0.01)
            months = [m["month"] for m in seeded.months() if m["month"] < MONTH][-3:]
            assert avg == pytest.approx(sum(spend(seeded, "month=? AND category=?", m, l["category"]) for m in months) / 3, abs=0.02)
            assert abs(now - avg) / avg >= insights.CHANGE_THRESHOLD
        if l["kind"] == "budget":
            assert seeded.summary(MONTH)["budgets"][l["category"]] in l["amounts"]


def test_most_visited_and_biggest_everyday(seeded):
    d = insights.build(seeded, MONTH, demo=True, today=NOW.date())
    counts = {r[0]: r[1] for r in seeded.db.execute(
        "SELECT merchant, sum(spend>0) FROM transactions WHERE month=? AND counted=1 AND spend>0 GROUP BY merchant_key", (MONTH,))}
    mv = d["most_visited"]
    assert mv["count"] == max(counts.values()) and counts[mv["merchant"]] == mv["count"]
    assert mv["merchant"] != "Landlord"
    big = d["biggest_everyday"]
    assert big["category"] not in d["fixed_keys"] and big["merchant"] != "Landlord"
    assert big["amount"] == seeded.db.execute(
        "SELECT max(spend) FROM transactions WHERE month=? AND counted=1 AND category NOT IN ('housing','bills','subscriptions')",
        (MONTH,)).fetchone()[0]


def test_open_month_compares_the_same_days(seeded):
    d = insights.build(seeded, MONTH, demo=False, today=date(2026, 10, 26))
    assert d["in_progress"] is True and d["elapsed_days"] == 26
    assert d["previous_spent_to_date"] == spend(seeded, "month=? AND CAST(substr(occurred_at,9,2) AS INT) <= 26", PREV)
    assert 0 < d["previous_spent_to_date"] < seeded.summary(PREV)["spent"]
    assert d["review"] == []
    assert all("usual by this point" in l["text"] for l in d["lines"] if l["kind"] == "change")
    # Later in the month the day range follows today; past the month it is closed.
    assert insights.build(seeded, MONTH, demo=False, today=date(2026, 10, 30))["elapsed_days"] == 30
    assert insights.build(seeded, MONTH, demo=False, today=date(2026, 11, 2))["in_progress"] is False


def test_missing_fixed_bill_only_while_the_month_runs(seeded):
    row = seeded.db.execute("SELECT id FROM transactions WHERE month=? AND merchant_key LIKE 'du %' OR (month=? AND merchant='Du')",
                            (MONTH, MONTH)).fetchone()
    assert row, "the example data pays a Du bill every month"
    seeded.correct(row["id"], hidden=True, remember=False)  # this month's bill 'didn't happen'
    try:
        open_month = insights.build(seeded, MONTH, demo=False, today=date(2026, 10, 26))
        missing = [l for l in open_month["lines"] if l["kind"] == "missing"]
        assert missing and missing[0]["text"].startswith("Du") and missing[0]["amounts"] == [349.0]
        assert missing[0]["to"] == "activity" and missing[0]["category"] == "bills"
        early = insights.build(seeded, MONTH, demo=False, today=date(2026, 10, 10))  # before its usual date
        assert not [l for l in early["lines"] if l["kind"] == "missing"]
        closed = insights.build(seeded, MONTH, demo=True, today=date(2026, 10, 26))
        assert not [l for l in closed["lines"] if l["kind"] == "missing"]
    finally:
        seeded.correct(row["id"], hidden=False, remember=False)


def test_closed_month_in_review(seeded):
    d = insights.build(seeded, PREV, demo=False, today=date(2026, 10, 26))
    s = seeded.summary(PREV)
    assert d["in_progress"] is False
    assert len(d["review"]) == 3
    total, move, savings = d["review"]
    assert total["kind"] == "total" and total["amounts"] == [s["spent"]] and "August" in total["text"]
    assert move["kind"] == "move" and move["category"] not in d["fixed_keys"] and move["to"] == "category"
    assert savings["kind"] == "savings" and "27%" in savings["text"]
    assert savings["amounts"] == [pytest.approx(s["received"] - s["spent"] - s["moved"], abs=0.01)]


def test_trends_window_is_everyday_only(seeded):
    d = insights.build(seeded, MONTH, demo=True, today=NOW.date(), months=3)
    t = seeded.trends(MONTH, 3)
    assert d["months"] == t["months"] and len(d["everyday_months"]) == 3
    for m, everyday, spent in zip(d["months"], d["everyday_months"], t["spent"]):
        assert everyday == pytest.approx(spend(seeded, "month=? AND category NOT IN ('housing','bills','subscriptions')", m), abs=0.01)
        assert everyday < spent
    assert len(d["weekday_everyday"]) == 7
    assert all(e <= w + 0.01 for e, w in zip(d["weekday_everyday"], t["weekday"]))
    assert max(d["weekday_everyday"]) < 1000  # no rent day crowning a weekday


# ---- the route --------------------------------------------------------------------

@pytest.fixture(scope="module")
def client(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("INBOX_LEDGER_DATA", str(tmp_path_factory.mktemp("insights-api")))
    mp.setenv("LEDGER_TODAY", "2026-10-26")
    seed = config.open_store()
    seed.add_messages(demo.generate(months=4, now=NOW))
    for key, limit in demo.DEMO_BUDGETS.items():
        seed.set_budget(key, limit)
    seed.rebuild()
    seed.db.close()
    from inbox_ledger import api
    api = importlib.reload(api)
    yield TestClient(api.app)
    api.store.db.close()
    mp.undo()


def test_insights_route(client):
    d = client.get("/api/insights", params={"month": MONTH}).json()
    assert d["month"] == MONTH and len(d["lines"]) >= 3
    assert d["most_visited"]["brand"] and d["most_visited"]["brand"]["key"]
    assert d["in_progress"] is True and d["elapsed_days"] == 26  # a plain data dir is real data, pinned to LEDGER_TODAY
    s = client.get("/api/summary", params={"month": MONTH}).json()
    assert d["fixed"] + d["everyday"] == pytest.approx(s["spent"], abs=0.01)
    assert client.get("/api/insights").status_code == 422
    assert client.get("/api/insights", params={"month": "nope"}).status_code == 400
    assert len(client.get("/api/insights", params={"month": MONTH, "months": 2}).json()["everyday_months"]) == 2
