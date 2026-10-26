"""Plan: recurring detection, pay-later instalments, the projection's arithmetic and the API."""
import importlib
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from inbox_ledger import config, demo, plan
from tests.helpers import card

from inbox_ledger import demo as _demo

DU = next(r[1] for r in _demo._RECURRING if r[0].startswith("DU "))
ETISALAT = next(r[1] for r in _demo._RECURRING if r[0].startswith("ETISALAT"))

NOW = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)  # demo data runs to 10 Oct, noon in Dubai
TODAY = date(2026, 10, 10)


@pytest.fixture
def seeded(store):
    store.add_messages(demo.generate(months=6, seed=7, now=NOW))
    store.rebuild()
    return store


def check_sum(p: dict) -> None:
    """Every figure the page shows must add up."""
    t = p["totals"]
    assert t["buffer"] == (t["money_in"] + t["expected_in"] - t["spent"] - t["expected"] - t["planned"]
                           - t["allowances"] - t["goal"])
    counted = [x for x in p["items"] if x["counts"]]
    assert t["expected"] == sum(plan._whole(x["amount"]) for x in counted if x["kind"] in ("recurring", "paylater"))
    assert t["planned"] == sum(plan._whole(x["amount"]) for x in counted if x["kind"] == "planned")
    assert t["expected_in"] == sum(plan._whole(x["amount"]) for x in counted if x["kind"] == "income")
    assert t["allowances"] == sum(a["amount"] for a in p["allowances"])
    assert t["goal"] == p["goal"]["amount"]
    assert p["daily"][-1]["projected"] == t["buffer"]  # the chart ends on the verdict
    for x in counted:
        assert p["as_of"] <= x["date"] <= p["end"]


# ---- recurring detection ---------------------------------------------------------------

def test_recurring_finds_bills_not_shopping(seeded):
    found = {(r["direction"], r["merchant_key"]): r for r in plan.recurring(seeded, "2026-10")}
    keys = {k for _, k in found}
    assert {"landlord", "dewa", "du", "etisalat", "fitness first", "netflix.com", "spotify", "apple.com/bill",
            "openai chatgpt subscr"} <= keys
    assert ("in", "salary") in found
    # Everyday merchants, irregular ones and pay-later stores are not bills.
    assert not keys & {"careem food", "talabat", "arabica", "f45 training", "noon", "ikea", "namshi", "tabby"}
    du = found[("out", "du")]
    assert du["day"] == 21 and du["amount"] == DU and du["category"] == "bills" and du["seen"] >= 3
    assert 270 <= found[("out", "dewa")]["amount"] <= 330  # a variable bill (demo range): the median of recent ones
    assert found[("out", "netflix.com")]["currency"] == "USD"


def _card(store, n, merchant, amount, day, month):
    when = datetime(2026, month, day, 10, 0)
    store.add_messages([card(f"r{n}", merchant, f"{amount:.2f}", date=when.strftime("%Y-%m-%dT06:00:00Z"),
                             when=when.strftime("%d-%b-%Y %I:%M %p").upper())])


def test_recurring_rules(store):
    n = 0
    for month, (gym, phone, ad_hoc) in {6: (300, 3, 10), 7: (310, 4, 2), 8: (290, 2, 25), 9: (305, 6, 18)}.items():
        _card(store, n := n + 1, "IRON GYM DUBAI AE", gym, 4, month)        # steady: day 4 ± 0, amount ±4%
        _card(store, n := n + 1, "HELLO MOBILE DUBAI AE", 120, phone, month)    # day wanders by ≤4: still monthly
        _card(store, n := n + 1, "FLOWER SHOP DUBAI AE", 80, ad_hoc, month)  # same amount, any day: not a bill
    for month in (7, 8):
        _card(store, n := n + 1, "BOOK CLUB DUBAI AE", 50, 9, month)        # only twice in four months
    for month, amount in ((6, 100), (7, 100), (8, 160), (9, 40)):
        _card(store, n := n + 1, "ROAMING DUBAI AE", amount, 12, month)     # amounts swing more than 15%
    store.rebuild()
    keys = {r["merchant_key"] for r in plan.recurring(store, "2026-10")}
    assert keys == {"iron gym", "hello mobile"}


# ---- pay later -------------------------------------------------------------------------

def test_instalments_from_tabby_emails(seeded):
    due = plan.instalments(seeded, date(2026, 11, 30), TODAY)
    assert due and all(i["provider"] == "Tabby" for i in due)
    for i in due:
        assert 0 < i["amount"] <= i["remaining"] + 0.01
        assert i["store"] in ("Noon", "Namshi", "IKEA") and i["category"] == "shopping"
    # Never more than what is still owed on an order.
    by_order = {}
    for i in due:
        by_order.setdefault(i["order"], []).append(i)
    for parts in by_order.values():
        assert sum(p["amount"] for p in parts) <= parts[0]["remaining"] + 0.01


# ---- the plan --------------------------------------------------------------------------

def test_plan_adds_up(seeded):
    p = plan.plan(seeded, "2026-10", TODAY)
    assert p["status"] == "current" and p["days_left"] == 22 and p["as_of"] == "2026-10-10"
    check_sum(p)
    names = {x["merchant_key"] for x in p["items"] if x["counts"]}
    assert {"du", "etisalat", "spotify", "apple.com/bill", "openai chatgpt subscr"} <= names
    paid = {x["merchant_key"] for x in p["paid"]}
    assert {"landlord", "dewa", "fitness first", "netflix.com", "salary"} <= paid
    assert not names & paid  # what already happened is never expected again
    # Next month's rent shows on the timeline but isn't part of October's sum.
    rent = next(x for x in p["items"] if x["merchant_key"] == "landlord")
    assert rent["date"] == "2026-11-02" and not rent["counts"]
    # Allowances start from typical spend minus what's spent and what's already expected.
    for a in p["allowances"]:
        assert a["suggested"] == max(0, a["typical"] - a["spent"] - a["expected"])
        assert a["per_day"] == pytest.approx(a["amount"] / p["days_left"], abs=0.01)
    bills = next(a for a in p["allowances"] if a["category"] == "bills")
    assert bills["expected"] >= DU + ETISALAT  # du and Etisalat are still to come
    s = seeded.summary("2026-10")
    assert p["totals"]["money_in"] == round(s["received"]) and p["totals"]["spent"] == round(s["spent"])
    assert p["goal"] == {"amount": round(s["moved"]), "suggested": round(s["moved"]), "moved": round(s["moved"]),
                         "edited": False}


def test_planned_items_and_changes(seeded):
    m = "2026-10"
    before = plan.plan(seeded, m, TODAY)["totals"]
    dinner = plan.add_item(seeded, "Birthday dinner", 400, "2026-10-12", "dining")
    plan.add_item(seeded, "Old thing", 90, "2026-10-02", "shopping")        # already passed: not counted
    plan.add_item(seeded, "Flight deposit", 700, "2026-11-04", "travel")    # next month: timeline only
    p = plan.plan(seeded, m, TODAY)
    check_sum(p)
    assert p["totals"]["planned"] == 400 and p["totals"]["buffer"] == before["buffer"] - 400
    assert {x["name"]: x["counts"] for x in p["items"] if x["kind"] == "planned"} == \
        {"Birthday dinner": True, "Old thing": False, "Flight deposit": False}

    plan.update_item(seeded, dinner["id"], amount=350.5, date="2026-10-20")
    assert plan.plan(seeded, m, TODAY)["totals"]["planned"] == 351

    du = next(x for x in p["items"] if x["merchant_key"] == "du" and x["counts"])
    plan.set_override(seeded, du["key"], m, state="skip")
    p2 = plan.plan(seeded, m, TODAY)
    check_sum(p2)
    assert p2["totals"]["expected"] == p["totals"]["expected"] - DU
    assert not next(x for x in p2["items"] if x["key"] == du["key"])["included"]
    plan.set_override(seeded, du["key"], m, amount=500)
    p3 = plan.plan(seeded, m, TODAY)
    assert p3["totals"]["expected"] == p["totals"]["expected"] + (500 - DU)
    assert next(x for x in p3["items"] if x["key"] == du["key"])["suggested"] == DU

    plan.set_allowance(seeded, m, "dining", 250)
    plan.set_goal(seeded, m, 9000)
    p4 = plan.plan(seeded, m, TODAY)
    check_sum(p4)
    assert next(a for a in p4["allowances"] if a["category"] == "dining")["amount"] == 250
    assert p4["goal"]["amount"] == 9000 and p4["goal"]["edited"]

    plan.reset(seeded, m)
    p5 = plan.plan(seeded, m, TODAY)
    assert p5["totals"]["expected"] == p["totals"]["expected"] and not p5["goal"]["edited"]
    assert p5["totals"]["planned"] == 351  # one-offs stay
    assert plan.delete_item(seeded, dinner["id"]) and not plan.delete_item(seeded, dinner["id"])


def test_late_and_missed_bills(seeded):
    # On the 24th du (21st) is late but still expected; had it been 8+ days late, it'd count only if you say so.
    seeded.db.execute("DELETE FROM transactions WHERE merchant_key='du' AND month='2026-10'")
    p = plan.plan(seeded, "2026-10", date(2026, 10, 24))
    du = next(x for x in p["items"] if x["merchant_key"] == "du" and x["usual"].startswith("2026-10"))
    assert du["status"] == "late" and du["counts"] and du["date"] == "2026-10-24"
    p = plan.plan(seeded, "2026-10", date(2026, 10, 30))
    du = next(x for x in p["items"] if x["merchant_key"] == "du" and x["usual"].startswith("2026-10"))
    assert du["status"] == "missed" and not du["counts"]
    plan.set_override(seeded, du["key"], "2026-10", state="include")
    p = plan.plan(seeded, "2026-10", date(2026, 10, 30))
    assert next(x for x in p["items"] if x["key"] == du["key"])["counts"]
    check_sum(p)


def test_past_month(seeded):
    assert plan.plan(seeded, "2026-09", TODAY)["status"] == "past"


# ---- API -------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("INBOX_LEDGER_DATA", str(tmp_path_factory.mktemp("plan-data")))
    st = config.open_store()
    st.add_messages(demo.generate(months=6, seed=7, now=NOW))
    st.rebuild()
    st.db.close()
    from inbox_ledger import api
    api = importlib.reload(api)
    yield TestClient(api.app)
    api.store.db.close()
    mp.undo()


def test_api_plan(client):
    q = {"month": "2026-10", "today": "2026-10-10"}
    p = client.get("/api/plan", params=q).json()
    check_sum(p)
    du = next(x for x in p["items"] if x["merchant_key"] == "du")
    assert du["brand"] and du["brand"]["key"] == "du"
    assert next(x for x in p["items"] if x["merchant_key"] == "landlord")["brand"] is None  # a person, not a shop

    r = client.post("/api/plan/items", json={"name": "  Birthday   dinner ", "amount": 400, "date": "2026-10-12",
                                             "category": "dining"})
    item = r.json()
    assert r.status_code == 200 and item["name"] == "Birthday dinner"
    assert client.get("/api/plan", params=q).json()["totals"]["planned"] == 400
    assert client.patch(f"/api/plan/items/{item['id']}", json={"amount": 380}).json()["amount"] == 380
    assert client.post("/api/plan/items", json={"name": "x", "amount": -5, "date": "2026-10-12"}).status_code == 400
    assert client.post("/api/plan/items", json={"name": " ", "amount": 5, "date": "2026-10-12"}).status_code == 400
    assert client.post("/api/plan/items", json={"name": "x", "amount": 5, "date": "2026-10-12",
                                                "category": "nope"}).status_code == 400
    assert client.patch("/api/plan/items/99999", json={"amount": 1}).status_code == 404

    assert client.put(f"/api/plan/expected/{du['key']}", json={"state": "skip"}).json() == {"ok": True}
    assert not next(x for x in client.get("/api/plan", params=q).json()["items"] if x["key"] == du["key"])["counts"]
    assert client.put(f"/api/plan/expected/{du['key']}", json={"state": "maybe"}).status_code == 400
    assert client.put("/api/plan/expected/item:1", json={"state": "skip"}).status_code == 400

    assert client.put("/api/plan/allowances/dining", json={"month": "2026-10", "amount": 120}).json() == {"ok": True}
    assert client.put("/api/plan/allowances/nope", json={"month": "2026-10", "amount": 1}).status_code == 400
    assert client.put("/api/plan/goal", json={"month": "2026-10", "amount": 5000}).json() == {"ok": True}
    assert client.put("/api/plan/goal", json={"month": "October", "amount": 5000}).status_code == 400
    p = client.get("/api/plan", params=q).json()
    check_sum(p)
    assert p["goal"]["amount"] == 5000
    assert next(a for a in p["allowances"] if a["category"] == "dining")["amount"] == 120

    assert client.post("/api/plan/reset", params={"month": "2026-10"}).json() == {"ok": True}
    p = client.get("/api/plan", params=q).json()
    assert not p["goal"]["edited"] and next(x for x in p["items"] if x["key"] == du["key"])["counts"]
    assert client.delete(f"/api/plan/items/{item['id']}").json() == {"ok": True}
    assert client.delete(f"/api/plan/items/{item['id']}").status_code == 404
    assert client.get("/api/plan", params={"month": "2026-9"}).status_code == 400
