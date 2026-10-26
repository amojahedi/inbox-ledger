import importlib
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from inbox_ledger import config, demo, wishlist

from .helpers import card, salary

TODAY = date(2026, 10, 25)
NOW = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)


def manual(store, pace, saved=0.0):
    wishlist.save_settings(store.db, {"manual_pace": pace, "use_manual": True, "saved": saved})


# ---- the saving pace --------------------------------------------------------------

def test_pace_is_the_last_three_complete_months_with_income(store):
    store.add_messages(demo.generate(months=6, now=NOW))
    store.rebuild()
    p = wishlist.saving_pace(store, TODAY)
    assert [m["month"] for m in p["months"]] == ["2026-07", "2026-08", "2026-09"]  # October isn't over yet
    by = {m["month"]: m for m in store.months()}
    avg_in = round(sum(by[m]["received"] for m in ("2026-07", "2026-08", "2026-09")) / 3)
    avg_out = round(sum(by[m]["spent"] for m in ("2026-07", "2026-08", "2026-09")) / 3)
    assert (p["avg_in"], p["avg_out"], p["amount"]) == (avg_in, avg_out, avg_in - avg_out)
    assert avg_in == demo.SALARY and p["amount"] > 0
    for m in p["months"]:
        assert m["saved"] == pytest.approx(m["in"] - m["out"])


def test_pace_falls_back_to_fewer_months_and_skips_a_partial_first_month(store):
    store.add_messages([
        salary("s-aug", "2026-08-01T06:00:00Z"),  # Mashreq salary: AED 18,500
        card("c-aug", "CARREFOUR MOE", "500.00", "2026-08-12T10:00:00Z", "12-AUG-2026 02:00 PM"),
        salary("s-sep", "2026-09-01T06:00:00Z"),
        card("c-sep", "CARREFOUR MOE", "1500.00", "2026-09-12T10:00:00Z", "12-SEP-2026 02:00 PM"),
        card("c-oct", "CARREFOUR MOE", "99.00", "2026-10-02T10:00:00Z", "02-OCT-2026 02:00 PM"),
    ])
    store.rebuild()
    p = wishlist.saving_pace(store, TODAY)
    assert [m["month"] for m in p["months"]] == ["2026-08", "2026-09"]
    assert p["amount"] == 18500 - 1000

    # Emails that start mid-month: that month is incomplete, so it isn't averaged.
    store.add_messages([card("c-jul", "CARREFOUR MOE", "20.00", "2026-07-20T10:00:00Z", "20-JUL-2026 02:00 PM"),
                        salary("s-jul", "2026-07-21T06:00:00Z")])
    store.rebuild()
    assert [m["month"] for m in wishlist.saving_pace(store, TODAY)["months"]] == ["2026-08", "2026-09"]


def test_no_income_means_no_pace_until_you_give_one(store):
    store.add_messages([card("c1", "CARREFOUR MOE", "120.00", "2026-09-03T10:00:00Z", "03-SEP-2026 02:00 PM")])
    store.rebuild()
    wishlist.add(store.db, {"name": "AirPods Pro", "price": 999})
    p = wishlist.plan(store, TODAY)
    assert p["pace"]["source"] == "none" and p["pace"]["amount"] is None
    assert p["wishes"][0]["status"] == "never" and p["tip"] is None

    wishlist.save_settings(store.db, {"manual_pace": 500})
    p = wishlist.plan(store, TODAY)
    assert p["pace"]["source"] == "manual" and p["pace"]["amount"] == 500  # used without income, even if not "use_manual"
    assert p["wishes"][0]["months"] == pytest.approx(999 / 500, abs=1e-3)


def test_manual_pace_overrides_data_only_when_chosen(store):
    store.add_messages(demo.generate(months=4, now=NOW))
    store.rebuild()
    wishlist.save_settings(store.db, {"manual_pace": 1000})
    p = wishlist.plan(store, TODAY)
    assert p["pace"]["source"] == "data" and p["pace"]["manual"] == 1000
    wishlist.save_settings(store.db, {"use_manual": True})
    p = wishlist.plan(store, TODAY)
    assert p["pace"]["source"] == "manual" and p["pace"]["amount"] == 1000
    assert p["pace"]["auto"]["amount"] > 0  # Ledger's own estimate is still offered


# ---- predictions --------------------------------------------------------------------

def test_wishes_are_funded_cumulatively_in_priority_order(store):
    manual(store, 1000, saved=1500)
    a = wishlist.add(store.db, {"name": "AirPods Pro", "price": 999})
    b = wishlist.add(store.db, {"name": "Weekend in Georgia", "price": 4500})
    c = wishlist.add(store.db, {"name": "MacBook Air", "price": 5299})
    p = wishlist.plan(store, TODAY)
    w = {x["id"]: x for x in p["wishes"]}
    assert p["total"] == 999 + 4500 + 5299
    assert w[a["id"]]["status"] == "ready" and w[a["id"]]["progress"] == 1 and w[a["id"]]["needed"] == 0
    assert w[b["id"]]["covered"] == 501 and w[b["id"]]["progress"] == pytest.approx(501 / 4500, abs=1e-4)
    assert w[b["id"]]["needed"] == 999 + 4500 - 1500 and w[b["id"]]["months"] == pytest.approx(3.999)
    assert w[c["id"]]["cumulative"] == 10798 and w[c["id"]]["months"] == pytest.approx(9.298)
    assert w[c["id"]]["ready_date"] == "2027-08-04"  # 9.298 months (283 days) after 25 Oct 2026
    assert [x["ready_date"] for x in p["wishes"]] == sorted(x["ready_date"] for x in p["wishes"])

    wishlist.reorder(store.db, [c["id"], a["id"], b["id"]])
    p = wishlist.plan(store, TODAY)
    assert [x["id"] for x in p["wishes"]] == [c["id"], a["id"], b["id"]]
    assert p["wishes"][1]["status"] == "future"  # the savings now go to the MacBook first
    assert p["wishes"][0]["covered"] == 1500


def test_not_at_the_current_pace(store):
    manual(store, -200)
    wishlist.add(store.db, {"name": "Bike", "price": 2000})
    w = wishlist.plan(store, TODAY)["wishes"][0]
    assert w["status"] == "never" and w["months"] is None and w["ready_date"] is None


def test_target_dates(store):
    manual(store, 1000)
    first = wishlist.add(store.db, {"name": "Phone", "price": 3000})
    later = wishlist.add(store.db, {"name": "Watch", "price": 1500, "target": "2027-01-25"})
    p = wishlist.plan(store, TODAY)
    t = p["wishes"][1]["target_check"]
    # 4,500 in total by 25 Jan (3.02 months away) needs ≈1,490 a month: 490 more than the pace.
    assert t["on_track"] is False and t["months_left"] == pytest.approx(92 / (365.25 / 12), abs=1e-3)
    assert t["needed_per_month"] == pytest.approx(4500 / t["months_left"], abs=0.01)
    assert t["extra_per_month"] == pytest.approx(t["needed_per_month"] - 1000, abs=0.01)
    assert t["top_fixes"] is True  # on its own, 1,500 in three months fits the pace

    wishlist.update(store.db, later["id"], {"target": "2027-06-01"})
    t = wishlist.plan(store, TODAY)["wishes"][1]["target_check"]
    assert t["on_track"] is True and t["spare_per_month"] > 0 and t["extra_per_month"] is None

    wishlist.update(store.db, first["id"], {"target": "2026-10-01"})
    t = wishlist.plan(store, TODAY)["wishes"][0]["target_check"]
    assert t["passed"] is True and t["on_track"] is False


def test_tip_trims_the_biggest_discretionary_category(store):
    store.add_messages(demo.generate(months=6, now=NOW))
    store.rebuild()
    wishlist.add(store.db, {"name": "MacBook Air", "price": 30000})
    p = wishlist.plan(store, TODAY)
    tip = p["tip"]
    months = [m["month"] for m in p["pace"]["auto"]["months"]]
    t = store.trends("2026-09", 3)
    assert t["months"] == months
    averages = {k: sum(v) / 3 for k, v in t["categories"].items() if k in wishlist.DISCRETIONARY}
    assert tip["category"] == max(averages, key=averages.get)
    assert tip["monthly"] == pytest.approx(averages[tip["category"]], abs=0.01)
    assert tip["cut"] == pytest.approx(tip["monthly"] * 0.2, abs=0.01)
    assert tip["kind"] == "sooner" and tip["days_sooner"] > 0 and tip["wish"] == "MacBook Air"
    assert tip["ready_date"] < p["wishes"][0]["ready_date"]


# ---- the list -----------------------------------------------------------------------

def test_mark_as_bought_moves_it_and_spends_its_savings(store):
    manual(store, 1000, saved=1500)
    a = wishlist.add(store.db, {"name": "AirPods Pro", "price": 999})
    b = wishlist.add(store.db, {"name": "Bag", "price": 800})
    n = store.db.execute("SELECT count(*) FROM transactions").fetchone()[0]
    wishlist.set_bought(store.db, a["id"])
    p = wishlist.plan(store, TODAY)
    assert [w["id"] for w in p["wishes"]] == [b["id"]] and [w["id"] for w in p["bought"]] == [a["id"]]
    assert p["saved"] == 501 and p["bought"][0]["paid_from_saved"] == 999
    assert p["wishes"][0]["covered"] == 501
    assert store.db.execute("SELECT count(*) FROM transactions").fetchone()[0] == n  # no transaction made

    wishlist.set_bought(store.db, a["id"], False)  # undo: back on top, savings restored
    p = wishlist.plan(store, TODAY)
    assert [w["id"] for w in p["wishes"]] == [a["id"], b["id"]] and p["saved"] == 1500 and not p["bought"]


def test_validation(store):
    with pytest.raises(ValueError):
        wishlist.add(store.db, {"name": "  ", "price": 10})
    with pytest.raises(ValueError):
        wishlist.add(store.db, {"name": "Thing", "price": 0})
    with pytest.raises(ValueError):
        wishlist.add(store.db, {"name": "Thing", "price": 10, "link": "javascript:alert(1)"})
    with pytest.raises(ValueError):
        wishlist.add(store.db, {"name": "Thing", "price": 10, "target": "someday"})
    w = wishlist.add(store.db, {"name": "  Air   Pods ", "price": "999.004", "link": "apple.com/airpods"})
    assert (w["name"], w["price"], w["link"]) == ("Air Pods", 999.0, "https://apple.com/airpods")
    assert wishlist.clean_link("http://example.com/x?y=1") == "http://example.com/x?y=1"
    with pytest.raises(ValueError):
        wishlist.reorder(store.db, [w["id"], w["id"]])
    with pytest.raises(KeyError):
        wishlist.update(store.db, 999, {"name": "x"})
    with pytest.raises(ValueError):
        wishlist.save_settings(store.db, {"saved": -5})


def test_demo_seed_adds_example_wishes(store):
    demo.seed(store, months=3)
    p = wishlist.plan(store)
    assert [w["name"] for w in p["wishes"]] == ["AirPods Pro", "A weekend in Georgia", "MacBook Air"]
    assert p["wishes"][2]["target"] and p["saved"] > 0
    assert p["wishes"][0]["status"] == "ready"
    demo.seed(store, months=3)  # seeding again doesn't duplicate them
    assert len(wishlist.wishes(store.db)) == 3


# ---- API ------------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    mp = pytest.MonkeyPatch()
    mp.setenv("INBOX_LEDGER_DATA", str(tmp_path))
    seed = config.open_store()
    seed.add_messages(demo.generate(months=4))
    seed.rebuild()
    seed.db.close()
    from inbox_ledger import api
    api = importlib.reload(api)
    yield TestClient(api.app)
    api.store.db.close()
    api._close_demo()
    mp.undo()


def test_api_round_trip(client):
    p = client.get("/api/wishlist").json()
    assert p["wishes"] == [] and p["pace"]["source"] == "data" and p["pace"]["amount"] > 0

    r = client.post("/api/wishlist/wishes", json={"name": "AirPods Pro", "price": 999, "link": "apple.com"})
    assert r.status_code == 200 and r.json()["wishes"][0]["link"] == "https://apple.com"
    a = r.json()["wishes"][0]["id"]
    b = client.post("/api/wishlist/wishes", json={"name": "MacBook Air", "price": 5299, "target": "2027-03-01"}).json()["wishes"][1]["id"]
    assert client.post("/api/wishlist/wishes", json={"name": "x", "price": -1}).status_code == 400
    assert client.post("/api/wishlist/wishes", json={"name": "x", "price": 1, "link": "javascript:x"}).status_code == 400

    p = client.patch(f"/api/wishlist/wishes/{a}", json={"note": "noise cancelling", "target": None}).json()
    assert p["wishes"][0]["note"] == "noise cancelling"
    assert client.patch("/api/wishlist/wishes/999", json={"name": "x"}).status_code == 404

    p = client.put("/api/wishlist/order", json={"ids": [b, a]}).json()
    assert [w["id"] for w in p["wishes"]] == [b, a]
    assert client.put("/api/wishlist/order", json={"ids": [a]}).status_code == 400

    p = client.patch("/api/wishlist", json={"saved": 6000}).json()
    assert p["saved"] == 6000 and p["wishes"][0]["status"] == "ready"
    assert client.patch("/api/wishlist", json={"colour": "red"}).status_code == 400

    p = client.post(f"/api/wishlist/wishes/{b}/bought", json={"bought": True}).json()
    assert [w["id"] for w in p["bought"]] == [b] and p["saved"] == 6000 - 5299
    p = client.post(f"/api/wishlist/wishes/{b}/bought", json={"bought": False}).json()
    assert not p["bought"] and p["saved"] == 6000

    p = client.delete(f"/api/wishlist/wishes/{a}").json()
    assert [w["id"] for w in p["wishes"]] == [b]


def test_api_demo_area_has_its_own_wishlist(client):
    client.post("/api/wishlist/wishes", json={"name": "Mine", "price": 10})
    client.post("/api/demo")
    names = [w["name"] for w in client.get("/api/wishlist").json()["wishes"]]
    assert names == ["AirPods Pro", "A weekend in Georgia", "MacBook Air"]
    client.delete("/api/demo")
    assert [w["name"] for w in client.get("/api/wishlist").json()["wishes"]] == ["Mine"]
