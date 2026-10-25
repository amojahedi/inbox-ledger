from datetime import datetime, timezone

import pytest

from inbox_ledger.config import DEFAULTS
from inbox_ledger.parsing import RawMessage
from inbox_ledger.paylater import load_providers, open_orders, parse_event, same_order

from .helpers import card

TABBY = "notifications@tabby.ai"


def purchase(id="p1", date="2026-09-29T10:00:05Z", store="Demo Store", order="NADEMO0000000123456789"):
    body = (f" Thanks for choosing Tabby, Alex.\nYour order from {store} is confirmed and the first payment was successful.\n"
            f"[View details]\n\n| | {store} |\n\n| | Paid today |  64.21 |\n| | |\n| | 29 Oct, 2026 |  64.20 |\n| | |\n"
            f"| | 29 Nov, 2026 |  64.20 |\n| | |\n| | 29 Dec, 2026 |  64.20 |\n\n| |\n\n| Date of purchase | 29 Sep, 2026 |\n"
            f"| Order number | #{order[:21]} |\n| Total order amount |  256.81 |\n\n| Credit summary |\n| Loan amount |  256.81 |\n"
            f"| Upfront payment from borrower |  64.21 |\n| Total to be repaid by borrower |  192.60 |")
    return RawMessage(id, date, TABBY, f"Successful purchase at {store}", body)


def payment(id="q1", date="2026-10-29T09:00:03Z", store="Demo Store", order="NADEMO0000000123456789",
            paid="64.20", due="128.40"):
    body = (f" Thanks for your payment\nHere’s your receipt for {store}.\n[Manage payments]\nOrder# {order}\n\n"
            f"| Paid today |  {paid} |\n\n| Total due |  {due} |\n| Next payment | 29 Nov, 2026 |")
    return RawMessage(id, date, TABBY, "Thanks! Here’s your Tabby payment confirmation.", body)


def final(id="f1", date="2026-12-29T09:00:01Z", store="Demo Store", order="NADEMO0000000123456789"):
    body = (f" Thanks for the last payment\nYou've made all your payments from {store} successfully. Here's your receipt.\n"
            f"[Manage payments]\nOrder# {order}\n\n| Paid today |  64.20 |\n\n| Total paid |  256.81 |")
    return RawMessage(id, date, TABBY, "Thanks! Here’s your Tabby payment confirmation.", body)


def consolidated(id="c1", date="2026-10-29T09:00:02Z"):
    body = " Thanks for your payment\nHere's your consolidated receipt for multiple payments made.\n\n| Paid today |  2,415.80 |"
    return RawMessage(id, date, TABBY, "Here’s your Tabby payment receipt", body)


def full_refund(id="r1", date="2026-11-02T08:00:00Z", store="Demo Store", order="NADEMO0000000123456789"):
    body = (f" Your order was refunded\nWe have successfully refunded your order from {store}.\n\n"
            f"| Refunded to your card |  128.41 |\n| Order number | #{order[:21]} |")
    return RawMessage(id, date, TABBY, f"💰 You've received a refund from {store}", body)


@pytest.fixture
def providers():
    return load_providers(DEFAULTS / "paylater")


def test_parses_each_tabby_email(providers):
    p = parse_event(purchase(), providers)
    assert (p.kind, p.store, p.paid, p.total, p.remaining, p.instalments) == ("purchase", "Demo Store", 64.21, 256.81, 192.60, 4)
    assert p.order == "NADEMO000000012345678"  # truncated in purchase emails
    q = parse_event(payment(), providers)
    assert (q.kind, q.store, q.paid, q.remaining, q.order, q.next_due) == (
        "payment", "Demo Store", 64.20, 128.40, "NADEMO0000000123456789", "29 Nov, 2026")
    assert parse_event(final(), providers).kind == "final"
    c = parse_event(consolidated(), providers)
    assert (c.kind, c.paid, c.store) == ("consolidated", 2415.80, "")
    r = parse_event(full_refund(), providers)
    assert (r.kind, r.store, r.refunded, r.full_refund) == ("refund", "Demo Store", 128.41, True)


def test_order_ids_join_by_prefix():
    assert same_order("#NADEMO000000012345678", "NADEMO0000000123456789")
    assert not same_order("ABC", "ABCD")


def test_tabby_charge_takes_the_store_and_its_category(store):
    store.add_messages([
        card("m1", "Tabby dubai AE", amount="64.20", date="2026-10-29T09:00:01Z", when="29-OCT-2026 01:00 PM"),
        payment(store="Noon"),
        card("m2", "TABBY FZ LLC DUBAI AE", amount="2,415.80", date="2026-10-29T09:00:00Z", when="29-OCT-2026 01:00 PM"),
        consolidated(),
        card("m3", "Tabby dubai AE", amount="50.00", date="2026-10-20T09:00:00Z", when="20-OCT-2026 01:00 PM"),
    ])
    result = store.rebuild()
    assert result["unparsed"] == 0 and result["paylater"] == {"emails": 2, "matched": 2}
    txs = {t["amount"]: t for t in store.transactions()}
    noon = txs[64.20]
    assert (noon["merchant"], noon["category"], noon["extra"]["via"]) == ("Noon", "shopping", "Tabby")
    assert txs[2415.80]["merchant"] == "Tabby (several orders)"
    assert txs[50.0]["merchant"] == "Tabby" and txs[50.0]["extra"]["via"] == "Tabby"  # no email: left as-is
    assert len(store.transactions(via="tabby")) == 3


def test_learned_rule_on_the_real_store_applies_to_tabby_charges(store):
    store.add_messages([card("m1", "Tabby dubai AE", amount="64.20", date="2026-10-29T09:00:01Z",
                             when="29-OCT-2026 01:00 PM"), payment(store="Zen Corner")])
    store.rebuild()
    t = store.transactions()[0]
    store.correct(t["id"], category="health")
    assert store.rules()[0]["merchant_key"] == "zen corner"
    assert store.transactions()[0]["category"] == "health"


def test_summary_shows_paid_and_still_owed(store):
    store.add_messages([
        purchase(), card("m0", "Tabby dubai AE", amount="64.21", date="2026-09-29T10:00:00Z", when="29-SEP-2026 02:00 PM"),
        payment(), card("m1", "Tabby dubai AE", amount="64.20", date="2026-10-29T09:00:01Z", when="29-OCT-2026 01:00 PM"),
    ])
    store.rebuild()
    pl = store.summary("2026-10")["pay_later"][0]
    assert pl["provider"] == "Tabby" and pl["paid"] == 64.20 and pl["payments"] == 1
    assert pl["owed"] == 128.40 and pl["open_orders"][0]["store"] == "Demo Store"
    assert pl["open_orders"][0]["instalments"] == 4
    assert store.summary("2026-09")["pay_later"][0]["owed"] == 192.60


def test_final_payment_and_full_refund_close_orders():
    providers = load_providers(DEFAULTS / "paylater")
    evs = [parse_event(m, providers) for m in (purchase(), payment(), final())]
    assert open_orders(evs, datetime(2027, 1, 1, tzinfo=timezone.utc)) == []
    evs = [parse_event(m, providers) for m in (purchase(), full_refund())]
    assert open_orders(evs, datetime(2027, 1, 1, tzinfo=timezone.utc)) == []
