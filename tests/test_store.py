import pytest

from .helpers import card, debit_alert, salary, transfer_receipt

MONTH = "2026-10"


def by_merchant(store, key):
    return [t for t in store.transactions(limit=1000) if t["merchant_key"] == key]


def test_mirror_dedupe_hides_debit_alert(store):
    store.add_messages([transfer_receipt("t1"), debit_alert("d1")])
    result = store.rebuild()
    assert result["mirrors"] == 1 and result["unparsed"] == 0
    visible = store.transactions()
    assert [t["kind"] for t in visible] == ["transfer"]
    assert store.summary("2026-10")["spent"] == 70.0


def test_debit_alert_without_matching_transfer_stays_visible(store):
    store.add_messages([transfer_receipt("t1"), debit_alert("d1", amount="71.00")])
    store.rebuild()
    assert len(store.transactions()) == 2


def test_failed_transfer_counts_as_unparsed(store):
    store.add_messages([transfer_receipt("t1", status="Failed")])
    assert store.rebuild()["unparsed"] == 1


def test_keyword_categorization(store):
    store.add_messages([
        card("c1", "TALABAT DUBAI AE"), card("c2", "CARREFOUR MOE DUBAI AE"), card("c3", "SALIK DUBAI AE"),
        card("c4", "NETFLIX.COM SINGAPORE SG", "15.49", currency="USD"), card("c5", "ZEN CORNER 1182 DUBAI AE"),
        salary("s1"), transfer_receipt("t1"),
    ])
    store.rebuild()
    cats = {t["merchant_key"]: (t["category"], t["category_source"]) for t in store.transactions()}
    assert cats["talabat"] == ("dining", "rule")
    assert cats["carrefour moe"] == ("groceries", "rule")
    assert cats["salik"] == ("transport", "rule")
    assert cats["netflix.com"] == ("subscriptions", "rule")
    assert cats["zen corner"] == ("other", "default")
    assert cats["salary"] == ("income", "rule")
    assert cats["sara ahmed"] == ("people", "rule")


def test_foreign_currency_converted_to_base(store):
    store.add_messages([card("c1", "NETFLIX.COM SINGAPORE SG", "10.00", currency="USD")])
    store.rebuild()
    t = store.transactions()[0]
    assert (t["amount"], t["currency"], t["amount_base"]) == (10.0, "USD", 36.73)


def test_correct_remember_recategorizes_past_and_future(store):
    store.add_messages([card("c1", "ZEN CORNER 1182 DUBAI AE", "20.00"),
                        card("c2", "ZEN CORNER 1182 DUBAI AE", "30.00", date="2026-10-20T10:00:00Z")])
    store.rebuild()
    first = by_merchant(store, "zen corner")[0]
    store.correct(first["id"], category="health", remember=True)
    assert {t["category"] for t in by_merchant(store, "zen corner")} == {"health"}
    assert all(t["category_source"] == "learned" for t in by_merchant(store, "zen corner"))

    store.add_messages([card("c3", "ZEN CORNER 1182 DUBAI AE", "40.00", date="2026-10-22T10:00:00Z")])
    store.rebuild()
    zen = by_merchant(store, "zen corner")
    assert len(zen) == 3 and {t["category"] for t in zen} == {"health"}
    assert [r["merchant_key"] for r in store.rules()] == ["zen corner"]


def test_correct_without_remember_affects_one_transaction(store):
    store.add_messages([card("c1", "ZEN CORNER 1182 DUBAI AE", "20.00"),
                        card("c2", "ZEN CORNER 1182 DUBAI AE", "30.00", date="2026-10-20T10:00:00Z")])
    store.rebuild()
    first, other = by_merchant(store, "zen corner")
    store.correct(first["id"], category="health", remember=False)
    cats = {t["id"]: (t["category"], t["category_source"]) for t in by_merchant(store, "zen corner")}
    assert cats[first["id"]] == ("health", "manual")
    assert cats[other["id"]] == ("other", "default")
    assert store.rules() == []


def test_correct_unknown_transaction(store):
    with pytest.raises(KeyError):
        store.correct("nope", category="health")


def test_note_roundtrip(store):
    store.add_messages([card("c1", "ZEN CORNER 1182 DUBAI AE")])
    store.rebuild()
    store.correct(store.transactions()[0]["id"], note="birthday gift", remember=True)
    assert store.transactions()[0]["note"] == "birthday gift"
    assert store.transactions(q="birthday")[0]["merchant_key"] == "zen corner"


def test_internal_direction_rule_removes_from_spent_and_delete_rule_restores(store):
    store.add_messages([card("c1", "ZEN CORNER 1182 DUBAI AE", "20.00"), card("c2", "SALIK DUBAI AE", "50.00")])
    store.rebuild()
    assert store.summary(MONTH)["spent"] == 70.0
    zen = by_merchant(store, "zen corner")[0]
    store.correct(zen["id"], direction="internal")
    s = store.summary(MONTH)
    assert (s["spent"], s["moved"]) == (50.0, 20.0)
    assert by_merchant(store, "zen corner")[0]["category"] == "other"

    store.delete_rule("zen corner")
    s = store.summary(MONTH)
    assert (s["spent"], s["moved"]) == (70.0, 0.0)
    assert store.rules() == []


def test_budgets_roundtrip(store):
    store.add_messages([card("c1", "TALABAT DUBAI AE")])
    store.rebuild()
    store.set_budget("dining", 500)
    store.set_budget("transport", 300)
    assert store.summary(MONTH)["budgets"] == {"dining": 500.0, "transport": 300.0}
    store.set_budget("dining", 650)
    store.set_budget("transport", None)
    assert store.summary(MONTH)["budgets"] == {"dining": 650.0}
    store.set_budget("dining", 0)
    assert store.summary(MONTH)["budgets"] == {}


def test_summary_totals_and_previous_spent(store):
    store.add_messages([
        card("c1", "TALABAT DUBAI AE", "100.00", date="2026-10-02T10:00:00Z", when="02-OCT-2026 02:00 PM"),
        card("c2", "TALABAT DUBAI AE", "50.00", date="2026-10-03T10:00:00Z", when="03-OCT-2026 02:00 PM"),
        card("c3", "CARREFOUR DUBAI AE", "200.00", date="2026-10-04T10:00:00Z", when="04-OCT-2026 02:00 PM"),
        card("c4", "TALABAT DUBAI AE", "80.00", date="2026-09-10T10:00:00Z", when="10-SEP-2026 02:00 PM"),
        card("c5", "TALABAT DUBAI AE", "999.00", date="2026-08-10T10:00:00Z", when="10-AUG-2026 02:00 PM"),
        salary("s1"),
    ])
    store.rebuild()
    s = store.summary(MONTH)
    assert (s["spent"], s["received"], s["count"], s["previous_spent"]) == (350.0, 18500.0, 4, 80.0)
    assert s["currency"] == "AED"
    assert {c["category"]: (c["total"], c["count"]) for c in s["by_category"]} == {
        "dining": (150.0, 2), "groceries": (200.0, 1)}
    assert s["top_merchants"][0]["merchant"] == "Carrefour"
    assert [d["day"] for d in s["by_day"]] == ["2026-10-02", "2026-10-03", "2026-10-04"]
    assert s["uncategorized"] == 0
    assert [m["month"] for m in store.months()] == ["2026-08", "2026-09", "2026-10"]


def test_previous_month_wraps_year(store):
    store.add_messages([card("c1", "TALABAT DUBAI AE", "60.00", date="2025-12-10T10:00:00Z",
                             when="10-DEC-2025 02:00 PM")])
    store.rebuild()
    assert store.summary("2026-01")["previous_spent"] == 60.0


def test_add_messages_is_idempotent(store):
    msgs = [card("c1", "TALABAT DUBAI AE")]
    assert store.add_messages(msgs) == 1
    assert store.add_messages(msgs) == 0
    store.rebuild()
    store.rebuild()
    assert len(store.transactions()) == 1


def test_own_account_moves_hidden_on_request(store):
    store.add_messages([transfer_receipt("t1", kind="Own Account"), card("c1", "CAREEM FOOD DUBAI AE")])
    store.rebuild()
    assert {t["direction"] for t in store.transactions()} == {"internal", "out"}
    assert [t["direction"] for t in store.transactions(internal="hide")] == ["out"]
    assert [t["direction"] for t in store.transactions(internal="only")] == ["internal"]
    s = store.summary(MONTH)
    assert s["count"] == 1 and s["moved"] == 70.0


def test_taxi_is_separate_from_transport(store):
    store.add_messages([card("c1", "CAREEM RIDE DUBAI AE"), card("c2", "Hala Taxi Ras Al Khaimah AE"),
                        card("c3", "SALIK DUBAI AE"), card("c4", "CAREEM FOOD DUBAI AE")])
    store.rebuild()
    cats = {t["merchant_key"]: t["category"] for t in store.transactions()}
    assert cats == {"careem ride": "taxi", "hala taxi": "taxi", "salik": "transport", "careem food": "dining"}


def test_summary_biggest_purchase(store):
    store.add_messages([card("c1", "ZARA DUBAI AE", amount="420.00"), card("c2", "STARBUCKS DUBAI AE", amount="18.00")])
    store.rebuild()
    assert store.summary(MONTH)["biggest"]["merchant"] == "Zara"


def test_amount_rule_only_matches_that_amount(store):
    store.add_messages([card("c1", "CAREEM FOOD DUBAI AE", amount="32.50"),
                        card("c2", "CAREEM FOOD DUBAI AE", amount="82.10", date="2026-10-20T12:00:00Z")])
    store.rebuild()
    coffee = next(t for t in store.transactions() if t["amount"] == 32.50)
    store.correct(coffee["id"], category="coffee", match_amount=True)
    store.add_messages([card("c3", "CAREEM FOOD DUBAI AE", amount="32.50", date="2026-10-22T08:00:00Z")])
    store.rebuild()
    cats = sorted((t["amount"], t["category"]) for t in by_merchant(store, "careem food"))
    assert cats == [(32.50, "coffee"), (32.50, "coffee"), (82.10, "dining")]
    assert store.rules()[0]["amount"] == 32.50
    store.delete_rule("careem food", 32.50)
    assert {t["category"] for t in by_merchant(store, "careem food")} == {"dining"}


def test_amount_rule_beats_merchant_wide_rule(store):
    store.add_messages([card("c1", "CAREEM FOOD DUBAI AE", amount="32.50"),
                        card("c2", "CAREEM FOOD DUBAI AE", amount="82.10", date="2026-10-20T12:00:00Z")])
    store.rebuild()
    a, b = sorted(store.transactions(), key=lambda t: t["amount"])
    store.correct(b["id"], category="groceries")
    store.correct(a["id"], category="coffee", match_amount=True)
    assert sorted((t["amount"], t["category"]) for t in by_merchant(store, "careem food")) == [
        (32.50, "coffee"), (82.10, "groceries")]


def test_migrates_v1_merchant_rules(tmp_path, banks):
    import sqlite3
    from inbox_ledger.config import DEFAULTS
    from inbox_ledger.store import Categories, Store
    db = sqlite3.connect(tmp_path / "old.db")
    db.execute("CREATE TABLE merchant_rules (merchant_key TEXT PRIMARY KEY, category TEXT, direction TEXT, created_at TEXT)")
    db.execute("INSERT INTO merchant_rules VALUES ('zen corner', 'health', NULL, '2026-10-01')")
    db.commit(); db.close()
    store = Store(tmp_path / "old.db", banks, Categories.load(DEFAULTS / "categories.yaml"))
    store.add_messages([card("c1", "ZEN CORNER DUBAI AE")])
    store.rebuild()
    assert store.transactions()[0]["category"] == "health"
    assert store.rules()[0]["amount"] == 0


def test_custom_category_lifecycle(store, banks, tmp_path):
    from inbox_ledger.config import DEFAULTS
    from inbox_ledger.store import Categories, Store
    store.add_messages([card("c1", "ZEN CORNER DUBAI AE")])
    store.rebuild()
    pets = store.add_category("Pets", "aqua")
    assert pets["key"] == "pets" and store.categories.items[-2]["key"] == "pets"
    store.correct(store.transactions()[0]["id"], category="pets")
    store.set_budget("pets", 300)
    assert store.transactions()[0]["category"] == "pets"
    with pytest.raises(ValueError):
        store.add_category("pets")
    reopened = Store(tmp_path / "ledger.db", banks, Categories.load(DEFAULTS / "categories.yaml"))
    assert "pets" in reopened.categories.by_key
    store.delete_category("pets")
    assert store.transactions()[0]["category"] == "other"
    assert store.summary(MONTH)["budgets"] == {} and store.rules() == []
    with pytest.raises(KeyError):
        store.delete_category("dining")
