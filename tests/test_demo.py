import pytest

from inbox_ledger import demo
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
    assert len(salary) == 6 and {t.amount for t in salary} == {demo.SALARY} and {t.account for t in salary} == {"7710"}
    assert any(t.kind == "account_debit" and t.merchant_raw == "ATM / cash withdrawal" for t in txns)


def test_demo_has_unmatched_merchants(store):
    store.add_messages(generate(now=NOW))
    assert store.rebuild()["unparsed"] == 0
    other = {t["merchant_key"] for t in store.transactions(category="other", limit=5000)}
    assert {"al faris tailoring", "golden sands", "zen corner"} <= other


MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]


@pytest.mark.parametrize("seed", [3, 7, 11, 21, 42, 99])
def test_every_demo_month_adds_up(store, seed):
    """Salary 30,000 in, 8,000 saved, 8,000 rent, under 14,000 spent, and every screen's totals agree."""
    store.add_messages(generate(seed=seed, now=NOW))
    for category, limit in demo.DEMO_BUDGETS.items():
        store.set_budget(category, limit)
    store.rebuild()
    assert store.categories.fx["USD"] == demo.FX["USD"]  # the demo converts USD charges the way the store does
    months = store.months()
    trends = store.trends("2026-10")
    assert [m["month"] for m in months] == trends["months"] == MONTHS
    for i, m in enumerate(months):
        s = store.summary(m["month"])
        assert s["received"] == trends["received"][i] == demo.SALARY == 30000
        assert s["moved"] == trends["moved"][i] == demo.SAVING_TRANSFER == 8000
        assert 13700 <= s["spent"] <= 14000
        assert s["spent"] == m["spent"] == trends["spent"][i] == round(sum(c["total"] for c in s["by_category"]), 2)
        assert round(s["received"] - s["spent"] - s["moved"], 2) == round(30000 - 8000 - s["spent"], 2) > 8000
        by_cat = {c["category"]: c["total"] for c in s["by_category"]}
        assert by_cat["housing"] == demo.RENT == 8000
        for key, total in by_cat.items():
            detail = store.category_detail(m["month"], key)
            assert detail["total"] == total == round(sum(p["total"] for p in detail["places"]), 2)
            assert trends["categories"][key][i] == total
        for key, limit in demo.DEMO_BUDGETS.items():
            assert by_cat.get(key, 0) <= limit  # budgets sit just above a typical month, never below it
        assert all(by_cat.get(k, 0) >= 0.7 * demo.DEMO_BUDGETS[k] for k in ("dining", "coffee", "shopping", "bills")) \
            or "travel" in by_cat  # only a trip month spends noticeably less day to day
    assert store.summary("2026-10")["spent"] == demo.MONTH_TOTAL == 13900.00
    rent = store.transactions(category="housing", limit=100)
    assert len(rent) == 6 and {t["amount_base"] for t in rent} == {8000.0}
    assert all("landlord" in t["merchant"].lower() for t in rent)
