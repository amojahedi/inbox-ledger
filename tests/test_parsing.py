import pytest

from inbox_ledger.merchants import display_name, merchant_key
from inbox_ledger.parsing import parse_message

from .helpers import card, debit_alert, salary, transfer_receipt


def test_card_purchase(banks):
    t = parse_message(card("m1", "CAREEM FOOD DUBAI AE", "1,232.50"), banks)
    assert (t.kind, t.direction, t.amount, t.currency) == ("card_purchase", "out", 1232.50, "AED")
    assert t.account == "4021"
    assert t.merchant_key == "careem food" and t.merchant == "Careem Food"
    assert t.occurred_at == "2026-10-24T16:20"


def test_card_purchase_usd(banks):
    t = parse_message(card("m1", "NETFLIX.COM SINGAPORE SG", "15.49", currency="USD"), banks)
    assert (t.amount, t.currency, t.merchant_key) == (15.49, "USD", "netflix.com")


def test_card_local_time_matches_utc_plus_four(banks):
    t = parse_message(card("m1", "SPINNEYS DUBAI AE", date="2026-10-24T12:20:59Z", when="24-OCT-2026 04:20 PM"), banks)
    assert t.occurred_at == "2026-10-24T16:20"


def test_account_debit_long_form(banks):
    t = parse_message(debit_alert("m1", "45.00", "7710", short=False), banks)
    assert (t.kind, t.direction, t.amount, t.account) == ("account_debit", "out", 45.0, "7710")
    assert t.merchant == "Account to Account Transfer"
    assert t.occurred_at == "2026-10-16T17:56"


def test_account_debit_short_form(banks):
    t = parse_message(debit_alert("m1", "70.00", "3390"), banks)
    assert (t.kind, t.direction, t.amount, t.account) == ("account_debit", "out", 70.0, "3390")
    assert t.merchant_raw == "Aani Instant Payments (Local IPP Transfer)"


def test_salary_credit(banks):
    t = parse_message(salary("m1"), banks)
    assert (t.kind, t.direction, t.amount, t.account) == ("account_credit", "in", 18500.0, "7710")
    assert t.merchant_key == "salary"


def test_local_transfer(banks):
    t = parse_message(transfer_receipt("m1"), banks)
    assert (t.kind, t.direction, t.amount, t.currency, t.account) == ("transfer", "out", 70.0, "AED", "3390")
    assert t.counterparty == "SARA AHMED" and t.merchant_key == "sara ahmed"
    assert t.status == "Success"
    assert t.occurred_at == "2026-10-16T17:54"


def test_own_account_transfer_is_internal(banks):
    t = parse_message(transfer_receipt("m1", kind="Own Account", src="7710", amount="45.00"), banks)
    assert (t.kind, t.direction, t.amount, t.account) == ("transfer", "internal", 45.0, "7710")
    assert t.counterparty == "Alex Demo"


def test_failed_transfer_is_ignored(banks):
    assert parse_message(transfer_receipt("m1", status="Failed"), banks) is None


def test_unknown_sender_and_body(banks):
    msg = card("m1", "X")
    msg.sender = "promo@example.com"
    assert parse_message(msg, banks) is None
    msg = card("m1", "X")
    msg.body = "Your statement is ready."
    assert parse_message(msg, banks) is None


@pytest.mark.parametrize("raw,key", [
    ("NOON FOOD DUBAI GB", "noon food"),
    ("Hala Taxi Ras Al Khaimah AE", "hala taxi"),
    ("Dubai Mall Dubai AE", "dubai mall"),
    ("SPOTIFY* PREMIUM +4686150500 SE", "spotify premium"),
])
def test_merchant_key(raw, key):
    assert merchant_key(raw) == key


def test_display_name_title_cases_shouting():
    assert display_name("NOON FOOD DUBAI GB") == "Noon Food"


def test_amount_without_leading_zero(banks):
    from .helpers import card
    t = parse_message(card("c1", "PARKING METER +97143000000 AE", amount=".50"), banks)
    assert t and t.amount == 0.5


def test_account_debit_with_space_after_colon(banks):
    from inbox_ledger.parsing import RawMessage
    body = ("Your AC No: XXXXXXXX3390 is debited with AED 120.00 for Online Local Funds Transfer "
            "(Charges & VAT incl. if applicable). Login to Online Banking for details.")
    t = parse_message(RawMessage("d9", "2026-10-01T10:00:00Z", "MashreqAlerts@mashreq.com", "Transaction Notification", body), banks)
    assert t and t.account == "3390" and t.amount == 120.0 and t.merchant_raw.startswith("Online Local Funds Transfer")
