"""Totals must reconcile: refunds net out of spending, transfers that cancel are settled, hidden rows
vanish from every total, and renames stick."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from inbox_ledger.config import DEFAULTS
from inbox_ledger.demo import generate
from inbox_ledger.parsing import RawMessage
from inbox_ledger.store import Categories, Store

from .test_paylater import TABBY, full_refund, payment, purchase

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)


def at(day: str, hour: int = 12) -> str:
    return f"{day}T{hour - 4:02d}:00:00Z"  # Dubai is UTC+4


def buy(id: str, merchant: str, amount: float, day: str, hour: int = 12) -> RawMessage:
    when = datetime.strptime(f"{day} {hour}", "%Y-%m-%d %H").strftime("%d-%b-%Y %I:00 %p").upper()
    body = (f"Your NEO VISA Debit Card Card ending with 4021 was used for a purchase of AED {amount:.2f} "
            f"at {merchant} on {when}. Available limit is AED 2,399.14")
    return RawMessage(id, at(day, hour), "MashreqAlerts@mashreq.com", "Transaction Confirmation on Mashreq Card", body)


def refund(id: str, merchant: str, amount: float, day: str) -> RawMessage:
    body = f"Card ending with 4021 refund credited AED {amount:.2f} from {merchant}."
    return RawMessage(id, at(day), "MashreqAlerts@mashreq.com", "Refund", body)


def send(id: str, to: str, amount: float, day: str) -> RawMessage:
    body = (f"Your money transfer request was processed successfully * Transfer typeLocal AED * "
            f"From Account********3390 * Reference numberMLC0101260000001 * Transaction date{day} 17:54:10 * "
            f"Destination countryUNITED ARAB EMIRATES * To account {to} *******************0001 * "
            f"Rate1 AED = 1.00000 AED * Transfer amountAED {amount:.2f} * Amount to be debitedAED {amount:.2f} * "
            f"Status Success")
    return RawMessage(id, at(day), "MashreqDigital@mashreq.com", "Local AED Transfer request via Mobile Banking", body)


def credit(id: str, sender: str, amount: float, day: str) -> RawMessage:
    body = (f"Amount of AED {amount:.2f} has been credited to your Mashreq account no. XXXXXXXX7710 "
            f"for {sender}. Login to Online Banking for details.")
    return RawMessage(id, at(day), "MashreqAlerts@mashreq.com", "Transaction Notification", body)


def salary(id: str, day: str = "2026-10-01") -> RawMessage:
    body = ("Amount of AED 18,500.00 has been credited to your Mashreq account no. XXXXXXXX7710 for Salary. "
            "Login to Online Banking for details.")
    return RawMessage(id, at(day), "MashreqAlerts@mashreq.com", "Transaction Notification", body)


def load(store, *msgs):
    store.add_messages(msgs)
    store.rebuild()


def by_id(store) -> dict:
    """Transactions keyed like "Zara300.0"; credits get a minus sign ("Zara-120.0")."""
    return {t["merchant"] + ("-" if t["direction"] == "in" else "") + str(t["amount"]): t
            for t in store.transactions(internal="show")}


def cats(summary) -> dict:
    return {c["category"]: c["total"] for c in summary["by_category"]}


def assert_reconciles(store, month):
    s = store.summary(month)
    assert round(sum(c["total"] for c in s["by_category"]), 2) == s["spent"]
    assert round(sum(d["total"] for d in s["by_day"]), 2) == s["spent"]
    return s


# ---- refunds ------------------------------------------------------------------------

def test_refund_reduces_spending_in_the_category_of_the_purchase(store):
    load(store, buy("b1", "ZARA DUBAI AE", 300, "2026-10-03"), buy("b2", "CAREEM RIDE DUBAI AE", 40, "2026-10-04"),
         refund("r1", "ZARA DUBAI AE", 120, "2026-10-09"), salary("s1"))
    s = assert_reconciles(store, "2026-10")
    assert (s["spent"], s["received"]) == (220.0, 18500.0)  # 300 + 40 - 120; the refund is not income
    assert cats(s) == {"shopping": 180.0, "taxi": 40.0}
    assert s["by_day"][-1] == {"day": "2026-10-09", "total": -120.0}
    assert s["top_merchants"][0]["merchant"] == "Zara" and s["top_merchants"][0]["total"] == 180.0
    rows = by_id(store)
    r, p = rows["Zara-120.0"], rows["Zara300.0"]
    assert r["extra"]["refund_of"] == p["id"] and p["extra"]["refunded_by"] == r["id"]
    assert (r["category"], r["spend"], r["income"]) == ("shopping", -120.0, 0.0)


def test_refund_takes_the_category_the_purchase_was_corrected_to(store):
    load(store, buy("b1", "ZEN CORNER 1182 DUBAI AE", 90, "2026-10-03"), refund("r1", "ZEN CORNER 1182 DUBAI AE", 90, "2026-10-05"))
    assert cats(store.summary("2026-10")) == {}
    purchase_row = next(t for t in store.transactions() if t["direction"] == "out")
    store.correct(purchase_row["id"], category="health", remember=False)
    assert {t["category"] for t in store.transactions()} == {"health"}
    assert store.summary("2026-10")["spent"] == 0.0


def test_refund_lands_in_its_own_month(store):
    load(store, buy("b1", "ZARA DUBAI AE", 300, "2026-09-28"), refund("r1", "ZARA DUBAI AE", 300, "2026-10-04"))
    assert store.summary("2026-09")["spent"] == 300.0
    s = store.summary("2026-10")
    assert (s["spent"], cats(s)) == (-300.0, {"shopping": -300.0})
    assert store.summary("2026-10")["previous_spent"] == 300.0


def test_refund_matching_rules(store):
    load(store,
         buy("b1", "ZARA DUBAI AE", 100, "2026-01-02"),   # 181 days before the refund of 100: too old
         buy("b2", "ZARA DUBAI AE", 500, "2026-06-01"),
         buy("b3", "ZARA DUBAI AE", 80, "2026-06-10"),    # smaller than any refund below
         buy("b4", "ZARA DUBAI AE", 500, "2026-06-20"),
         refund("r1", "ZARA DUBAI AE", 150, "2026-06-25"),  # closest earlier purchase that is big enough: b4
         refund("r2", "ZARA DUBAI AE", 500, "2026-07-01"),  # b4 is used: b2
         refund("r3", "ZARA DUBAI AE", 100, "2026-07-02"),  # nothing in range and unused
         refund("r4", "ZARA DUBAI AE", 500, "2026-07-03"))  # both 500s are used
    rows = {t["id"]: t for t in store.transactions(internal="show")}
    refunds = sorted((t for t in rows.values() if t["direction"] == "in"), key=lambda t: t["occurred_at"])
    got = [rows[t["extra"]["refund_of"]]["occurred_at"][:10] if "refund_of" in t["extra"] else None for t in refunds]
    assert got == ["2026-06-20", "2026-06-01", None, None]
    assert all(t["extra"]["refund"] for t in refunds)
    assert store.summary("2026-07")["spent"] == -1100.0  # unmatched refunds still reduce spending


def test_each_purchase_is_refunded_once_exact_amount_first(store):
    load(store, buy("b1", "ZARA DUBAI AE", 100, "2026-10-01"), buy("b2", "ZARA DUBAI AE", 250, "2026-10-02"),
         refund("r1", "ZARA DUBAI AE", 100, "2026-10-05"))
    rows = by_id(store)  # the closer purchase is bigger, but the exact amount wins
    assert rows["Zara100.0"]["extra"]["refunded_by"] == rows["Zara-100.0"]["id"]
    assert "refunded_by" not in rows["Zara250.0"]["extra"]


def test_unmatched_refund_still_reduces_its_merchants_category(store):
    load(store, buy("b1", "TALABAT DUBAI AE", 60, "2026-10-02"), refund("r1", "CARREFOUR DUBAI AE", 45, "2026-10-04"))
    s = assert_reconciles(store, "2026-10")
    assert (s["spent"], s["received"]) == (15.0, 0.0)
    assert cats(s) == {"dining": 60.0, "groceries": -45.0}
    r = next(t for t in store.transactions() if t["direction"] == "in")
    assert r["extra"] == {"refund": True} and "refund_of" not in r["extra"]


def test_refund_that_names_no_shop_matches_by_amount(store):
    body = "Card ending with 4021 has been credited with a reversal of AED 75.00."
    load(store, buy("b1", "TALABAT DUBAI AE", 75, "2026-10-02"), buy("b2", "ZARA DUBAI AE", 75, "2026-10-03"),
         RawMessage("r1", at("2026-10-05"), "MashreqAlerts@mashreq.com", "Reversal", body))
    r = next(t for t in store.transactions() if t["direction"] == "in")
    assert (r["merchant"], r["category"]) == ("Zara", "shopping")  # closest earlier purchase of that amount
    assert store.summary("2026-10")["spent"] == 75.0


def test_a_refund_to_a_hidden_purchase_does_not_match_it(store):
    load(store, buy("b1", "ZARA DUBAI AE", 100, "2026-10-01"), refund("r1", "ZARA DUBAI AE", 100, "2026-10-02"))
    p = next(t for t in store.transactions() if t["direction"] == "out")
    store.correct(p["id"], hidden=True)
    r = store.transactions()[0]
    assert "refund_of" not in r["extra"] and store.summary("2026-10")["spent"] == -100.0


def tabby_card(id, amount, day, hour=13):
    return buy(id, "TABBY FZ LLC DUBAI AE", float(amount), day, hour)


def tabby_order(store):
    store.add_messages([tabby_card("m1", "64.21", "2026-09-29", 14), purchase("p1", "2026-09-29T10:00:05Z"),
                        tabby_card("m2", "64.20", "2026-10-29", 13), payment("q1", "2026-10-29T09:00:03Z")])


def test_tabby_refund_without_a_bank_credit_is_recorded_from_the_email(store):
    tabby_order(store)
    store.add_messages([full_refund("r1", "2026-11-02T08:00:00Z")])
    store.rebuild()
    assert store.summary("2026-10")["spent"] == 64.20
    s = store.summary("2026-11")
    assert (s["spent"], s["received"], cats(s)) == (-128.41, 0.0, {"other": -128.41})  # Demo Store is in no category
    refund_row = next(t for t in store.transactions() if t["direction"] == "in")
    assert refund_row["merchant"] == "Demo Store" and refund_row["extra"]["via"] == "Tabby"
    assert refund_row["extra"]["refund_of"]
    assert store.rebuild()["transactions"] == 3  # rebuilding does not add it twice


def test_tabby_refund_with_a_bank_credit_counts_once(store):
    tabby_order(store)
    store.add_messages([full_refund("r1", "2026-11-02T08:00:00Z"),
                        refund("r2", "TABBY FZ LLC DUBAI AE", 128.41, "2026-11-04")])
    store.rebuild()
    credits = [t for t in store.transactions() if t["direction"] == "in"]
    assert len(credits) == 1 and credits[0]["merchant"] == "Demo Store" and credits[0]["id"]
    assert store.summary("2026-11")["spent"] == -128.41
    assert cats(store.summary("2026-11")) == {"other": -128.41} and "refund_of" in credits[0]["extra"]


# ---- transfers that cancel out ------------------------------------------------------

def test_money_sent_and_returned_is_settled_and_hidden(store):
    load(store, send("t1", "SARA AHMED", 150, "2026-10-03"), credit("c1", "Sara Ahmed", 150, "2026-10-12"),
         buy("b1", "TALABAT DUBAI AE", 60, "2026-10-04"), salary("s1"))
    s = assert_reconciles(store, "2026-10")
    assert (s["spent"], s["received"], s["count"]) == (60.0, 18500.0, 2)
    assert cats(s) == {"dining": 60.0}
    assert {t["merchant_raw"] for t in store.transactions()} == {"TALABAT DUBAI AE", "Salary"}
    settled = store.transactions(show="settled")
    assert len(settled) == 2 and len({t["extra"]["settled"] for t in settled}) == 1
    assert {t["direction"] for t in settled} == {"out", "in"}


def test_settlement_works_either_way_round_and_over_several_transfers(store):
    load(store, credit("c1", "LAYLA HASSAN", 100, "2026-10-02"), send("t1", "Layla Hassan", 100, "2026-10-09"),
         send("t2", "NOUR KHALIL", 40, "2026-10-03"), send("t3", "NOUR KHALIL", 60, "2026-10-04"),
         credit("c2", "Payment from nour khalil", 100, "2026-10-20"))
    s = store.summary("2026-10")
    assert (s["spent"], s["received"], s["count"]) == (0.0, 0.0, 0)
    assert len(store.transactions(show="settled")) == 5


def test_transfers_more_than_45_days_apart_do_not_cancel(store):
    load(store, send("t1", "SARA AHMED", 150, "2026-08-01"), credit("c1", "SARA AHMED", 150, "2026-09-20"))
    assert not store.transactions(show="settled")
    assert store.summary("2026-08")["spent"] == 150.0 and store.summary("2026-09")["received"] == 150.0


def test_only_the_same_person_settles(store):
    load(store, send("t1", "SARA AHMED", 150, "2026-10-03"), credit("c1", "NOUR KHALIL", 150, "2026-10-05"))
    s = store.summary("2026-10")
    assert (s["spent"], s["received"]) == (150.0, 150.0)


def test_partial_payback_reduces_spending_on_people(store):
    load(store, send("t1", "SARA AHMED", 200, "2026-10-03"), credit("c1", "SARA AHMED", 80, "2026-10-12"))
    s = assert_reconciles(store, "2026-10")
    assert (s["spent"], s["received"]) == (120.0, 0.0)
    assert cats(s) == {"people": 120.0}
    back = next(t for t in store.transactions() if t["direction"] == "in")
    assert (back["category"], back["extra"]["payback"], back["spend"], back["income"]) == ("people", True, -80.0, 0.0)
    # The rest arrives later and the whole thing cancels.
    store.add_messages([credit("c2", "SARA AHMED", 120, "2026-10-20")])
    store.rebuild()
    s = store.summary("2026-10")
    assert (s["spent"], s["received"], len(store.transactions(show="settled"))) == (0.0, 0.0, 3)


def test_more_than_was_sent_is_partly_income(store):
    load(store, send("t1", "SARA AHMED", 100, "2026-10-03"), credit("c1", "SARA AHMED", 130, "2026-10-12"))
    s = assert_reconciles(store, "2026-10")
    assert (s["spent"], s["received"]) == (0.0, 30.0)


# ---- didn't happen --------------------------------------------------------------------

def test_hidden_transactions_leave_every_total_and_survive_rebuilds(store):
    load(store, buy("b1", "TALABAT DUBAI AE", 60, "2026-10-04"), buy("b2", "ZARA DUBAI AE", 200, "2026-10-05"), salary("s1"))
    zara = next(t for t in store.transactions() if t["merchant"] == "Zara")
    store.correct(zara["id"], hidden=True)
    s = assert_reconciles(store, "2026-10")
    assert (s["spent"], s["count"], s["biggest"]["merchant"]) == (60.0, 2, "Talabat")
    assert [m["spent"] for m in store.months()] == [60.0]
    assert store.trends("2026-10")["spent"] == [60.0] and store.category_detail("2026-10", "shopping")["total"] == 0
    assert [t["merchant"] for t in store.transactions(show="hidden")] == ["Zara"]
    assert "Zara" not in {t["merchant"] for t in store.transactions()}
    store.rebuild()
    assert store.summary("2026-10")["spent"] == 60.0 and len(store.transactions(show="hidden")) == 1
    store.correct(zara["id"], hidden=False)
    assert store.summary("2026-10")["spent"] == 260.0 and not store.transactions(show="hidden")


def test_hiding_one_side_of_a_transfer_pair_unsettles_the_other(store):
    load(store, send("t1", "SARA AHMED", 150, "2026-10-03"), credit("c1", "SARA AHMED", 150, "2026-10-12"))
    back = next(t for t in store.transactions(show="settled") if t["direction"] == "in")
    store.correct(back["id"], hidden=True)
    assert store.summary("2026-10")["spent"] == 150.0 and not store.transactions(show="settled")


def test_hidden_flag_is_independent_of_remember(store):
    load(store, buy("b1", "ZARA DUBAI AE", 200, "2026-10-05"), buy("b2", "ZARA DUBAI AE", 90, "2026-10-06"))
    first = store.transactions()[1]
    store.correct(first["id"], hidden=True, remember=True)
    assert [t["amount"] for t in store.transactions()] == [90.0]
    assert store.rules() == []


# ---- rename ---------------------------------------------------------------------------

def test_rename_with_remember_covers_every_past_and_future_transaction(store):
    load(store, buy("b1", "ZEN CORNER 1182 DUBAI AE", 20, "2026-10-02"), buy("b2", "ZEN CORNER 1182 DUBAI AE", 30, "2026-10-03"))
    store.correct(store.transactions()[0]["id"], name="  Sunday   Tea House ", remember=True)
    assert {t["merchant"] for t in store.transactions()} == {"Sunday Tea House"}
    assert store.transactions()[0]["extra"]["original_merchant"] == "Zen Corner"
    assert {t["merchant_key"] for t in store.transactions()} == {"zen corner"}  # rules still find it
    store.add_messages([buy("b3", "ZEN CORNER 1182 DUBAI AE", 40, "2026-10-04")])
    store.rebuild()
    assert [t["merchant"] for t in store.transactions()] == ["Sunday Tea House"] * 3
    assert store.summary("2026-10")["top_merchants"][0]["merchant"] == "Sunday Tea House"
    assert len(store.transactions(q="sunday")) == 3 and len(store.transactions(q="zen corner")) == 3


def test_rename_without_remember_changes_one_transaction(store):
    load(store, buy("b1", "ZEN CORNER 1182 DUBAI AE", 20, "2026-10-02"), buy("b2", "ZEN CORNER 1182 DUBAI AE", 30, "2026-10-03"))
    newest = store.transactions()[0]
    store.correct(newest["id"], name="Birthday cake", remember=False)
    assert [t["merchant"] for t in store.transactions()] == ["Birthday cake", "Zen Corner"]
    store.rebuild()
    assert [t["merchant"] for t in store.transactions()] == ["Birthday cake", "Zen Corner"]
    store.correct(newest["id"], name="", remember=False)
    assert {t["merchant"] for t in store.transactions()} == {"Zen Corner"}


def test_rename_back_to_nothing_restores_the_original_everywhere(store):
    load(store, buy("b1", "ZEN CORNER 1182 DUBAI AE", 20, "2026-10-02"))
    tx = store.transactions()[0]
    store.correct(tx["id"], name="Tea", remember=True)
    store.correct(tx["id"], name="", remember=True)
    assert store.transactions()[0]["merchant"] == "Zen Corner"
    assert "original_merchant" not in store.transactions()[0]["extra"]


def test_rename_keeps_the_category_rules_working(store):
    load(store, buy("b1", "ZEN CORNER 1182 DUBAI AE", 20, "2026-10-02"))
    tx = store.transactions()[0]
    store.correct(tx["id"], name="Tea", category="health", remember=True)
    store.add_messages([buy("b2", "ZEN CORNER 1182 DUBAI AE", 25, "2026-10-03")])
    store.rebuild()
    assert {(t["merchant"], t["category"]) for t in store.transactions()} == {("Tea", "health")}


# ---- the totals add up ----------------------------------------------------------------

def test_demo_months_reconcile(store):
    store.add_messages(generate(months=6, now=NOW))
    store.rebuild()
    months = [m["month"] for m in store.months()]
    assert len(months) == 6
    for month in months:
        s = assert_reconciles(store, month)
        spent_rows = round(sum(t["amount_base"] for t in store.transactions(month=month, internal="hide", limit=9999)
                               if t["direction"] == "out"), 2)
        assert s["spent"] == spent_rows
        left = s["received"] - s["spent"] - s["moved"]  # "left" on the overview: came in - spent - put aside
        moved = sum(t["amount_base"] for t in store.transactions(month=month, internal="only", limit=9999))
        assert left == pytest.approx(s["received"] - spent_rows - moved, abs=0.005)
        assert s["moved"] == round(moved, 2)
        assert store.months()[months.index(month)]["spent"] == s["spent"]
        assert store.trends(month, 6)["spent"][-1] == s["spent"]


def test_a_messy_month_still_reconciles(store):
    load(store,
         salary("s1"), buy("b1", "ZARA DUBAI AE", 300, "2026-10-03"), refund("r1", "ZARA DUBAI AE", 120, "2026-10-09"),
         refund("r2", "NOON.COM DUBAI AE", 35.5, "2026-10-10"), buy("b2", "TALABAT DUBAI AE", 61.25, "2026-10-11"),
         send("t1", "SARA AHMED", 150, "2026-10-03"), credit("c1", "SARA AHMED", 150, "2026-10-12"),
         send("t2", "NOUR KHALIL", 90, "2026-10-04"), credit("c2", "NOUR KHALIL", 30, "2026-10-14"),
         buy("b3", "CAREEM RIDE DUBAI AE", 28, "2026-10-15"), buy("b4", "SALIK DUBAI AE", 50, "2026-10-16"))
    store.correct(next(t for t in store.transactions() if t["merchant"] == "Salik")["id"], hidden=True)
    s = assert_reconciles(store, "2026-10")
    assert s["spent"] == 300 - 120 - 35.5 + 61.25 + (90 - 30) + 28
    assert s["received"] == 18500.0
    detail = store.category_detail("2026-10", "shopping")
    assert detail["total"] == cats(s)["shopping"] == 144.5
    assert round(sum(p["total"] for p in detail["places"]), 2) == detail["total"]


def test_old_databases_are_upgraded_and_rebuilt(tmp_path, banks):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE raw_messages (id TEXT PRIMARY KEY, date TEXT, sender TEXT, subject TEXT, body TEXT)")
    db.execute("CREATE TABLE overrides (transaction_id TEXT PRIMARY KEY, category TEXT, direction TEXT, note TEXT)")
    db.execute("CREATE TABLE transactions (id TEXT PRIMARY KEY, message_id TEXT, bank TEXT, kind TEXT, direction TEXT,"
               " occurred_at TEXT, month TEXT, amount REAL, currency TEXT, amount_base REAL, account TEXT,"
               " merchant_raw TEXT, merchant_key TEXT, merchant TEXT, counterparty TEXT, status TEXT, pattern TEXT,"
               " extra TEXT, category TEXT, category_source TEXT, mirror_of TEXT, note TEXT DEFAULT '')")
    m = buy("b1", "ZARA DUBAI AE", 300, "2026-10-03")
    db.execute("INSERT INTO raw_messages VALUES (?,?,?,?,?)", (m.id, m.date, m.sender, m.subject, m.body))
    db.commit(); db.close()
    store = Store(path, banks, Categories.load(DEFAULTS / "categories.yaml"))
    assert store.summary("2026-10")["spent"] == 300.0
    store.correct(store.transactions()[0]["id"], hidden=True, name="x", remember=False)
    assert store.summary("2026-10")["spent"] == 0.0
