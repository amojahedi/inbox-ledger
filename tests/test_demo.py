from datetime import datetime, timezone

from inbox_ledger.demo import generate
from inbox_ledger.parsing import find_mirrors, parse_message

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)


def test_every_demo_message_parses(banks):
    from inbox_ledger.config import DEFAULTS
    from inbox_ledger.paylater import load_providers, parse_event
    providers = load_providers(DEFAULTS / "paylater")
    msgs = generate(months=6, now=NOW)
    bank_msgs = [m for m in msgs if "tabby" not in m.sender]
    assert len(bank_msgs) > 200 and len(msgs) > len(bank_msgs)
    parsed = [parse_message(m, banks) for m in bank_msgs]
    assert all(parsed)
    assert {t.bank for t in parsed} == {"Emirates NBD"} and not any(t.pattern.startswith("generic_") for t in parsed)
    assert {m.sender for m in bank_msgs} == {"alert@emiratesnbd.com", "OnlineBanking@emiratesnbd.com"}
    assert all(parse_event(m, providers) for m in msgs if "tabby" in m.sender)
    assert len({m.id for m in msgs}) == len(msgs)


def test_demo_is_deterministic_and_ends_now():
    a, b = generate(seed=3, now=NOW), generate(seed=3, now=NOW)
    assert a == b and a != generate(seed=4, now=NOW)
    assert a[0].date.startswith("2026-05-01") and a[-1].date <= "2026-10-25T09:00:00Z"
    assert [m.date for m in a] == sorted(m.date for m in a)


def test_transfers_cover_local_and_own_accounts(banks):
    txns = [parse_message(m, banks) for m in generate(now=NOW) if "tabby" not in m.sender]
    transfers = [t for t in txns if t.kind == "transfer"]
    assert transfers and {t.direction for t in transfers} == {"out", "internal"}
    assert all(t.account in {"7710", "3390"} for t in transfers)
    assert not find_mirrors(txns, banks)  # ENBD sends one email per transfer, so nothing is double counted


def test_demo_has_salary_and_cash_withdrawals(banks):
    txns = [parse_message(m, banks) for m in generate(now=NOW) if "tabby" not in m.sender]
    salary = [t for t in txns if t.kind == "account_credit"]
    assert len(salary) == 6 and {t.amount for t in salary} == {18500.0} and {t.account for t in salary} == {"7710"}
    assert any(t.kind == "account_debit" and t.merchant_raw == "ATM / cash withdrawal" for t in txns)


def test_demo_has_unmatched_merchants(store):
    store.add_messages(generate(now=NOW))
    assert store.rebuild()["unparsed"] == 0
    other = {t["merchant_key"] for t in store.transactions(category="other", limit=5000)}
    assert {"al faris tailoring", "golden sands", "zen corner"} <= other
