import importlib

import pytest
from fastapi.testclient import TestClient

from inbox_ledger import config, demo


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("INBOX_LEDGER_DATA", str(tmp_path_factory.mktemp("api-data")))
    seed = config.open_store()
    seed.add_messages(demo.generate(months=3))
    seed.rebuild()
    seed.db.close()
    from inbox_ledger import api
    api = importlib.reload(api)
    yield TestClient(api.app)
    api.store.db.close()
    mp.undo()


@pytest.fixture(scope="module")
def current(client) -> str:
    return client.get("/api/meta").json()["current"]


def test_meta(client):
    meta = client.get("/api/meta").json()
    assert meta["currency"] == "AED" and {"Mashreq", "Emirates NBD"} <= set(meta["banks"])
    assert len(meta["months"]) == 3
    assert meta["current"] == meta["months"][-1]["month"]
    keys = {c["key"] for c in meta["categories"]}
    assert {"dining", "groceries", "people", "other"} <= keys
    assert all({"key", "name", "color", "custom"} == set(c) for c in meta["categories"])


def test_summary(client, current):
    s = client.get("/api/summary", params={"month": current}).json()
    assert s["month"] == current and s["currency"] == "AED"
    assert s["received"] == 18500.0
    assert 0 < s["spent"] < 15000
    assert s["previous_spent"] > 0
    assert sum(c["total"] for c in s["by_category"]) == pytest.approx(s["spent"], abs=0.1)
    assert client.get("/api/summary").status_code == 422


def test_transactions_filters(client, current):
    everything = client.get("/api/transactions").json()
    month = client.get("/api/transactions", params={"month": current}).json()
    assert 0 < len(month) < len(everything)
    assert all(t["month"] == current for t in month)
    assert [t["occurred_at"] for t in month] == sorted((t["occurred_at"] for t in month), reverse=True)
    assert not any(t["mirror_of"] for t in everything)

    dining = client.get("/api/transactions", params={"category": "dining"}).json()
    assert dining and all(t["category"] == "dining" for t in dining)
    hits = client.get("/api/transactions", params={"q": "starbucks"}).json()
    assert hits and all("starbucks" in t["merchant_key"] for t in hits)


def test_patch_correction_and_rules(client):
    tx = client.get("/api/transactions", params={"q": "Zen Corner"}).json()[0]
    assert tx["category"] == "other"

    assert client.patch(f"/api/transactions/{tx['id']}", json={"category": "nonsense"}).status_code == 400
    assert client.patch(f"/api/transactions/{tx['id']}", json={"direction": "sideways"}).status_code == 400
    assert client.patch("/api/transactions/missing", json={"category": "health"}).status_code == 404

    assert client.patch(f"/api/transactions/{tx['id']}", json={"category": "health"}).json() == {"ok": True}
    zen = client.get("/api/transactions", params={"q": "Zen Corner"}).json()
    assert zen and {t["category"] for t in zen} == {"health"}

    rules = client.get("/api/rules").json()
    rule = next(r for r in rules if r["merchant_key"] == "zen corner")
    assert rule["category"] == "health" and rule["merchant"] == "Zen Corner"

    assert client.delete("/api/rules/zen corner").json() == {"ok": True}
    assert not any(r["merchant_key"] == "zen corner" for r in client.get("/api/rules").json())
    assert {t["category"] for t in client.get("/api/transactions", params={"q": "Zen Corner"}).json()} == {"other"}


def test_budgets(client, current):
    assert client.put("/api/budgets/dining", json={"monthly": 900}).json() == {"ok": True}
    assert client.get("/api/summary", params={"month": current}).json()["budgets"] == {"dining": 900.0}
    assert client.put("/api/budgets/nonsense", json={"monthly": 1}).status_code == 400
    client.put("/api/budgets/dining", json={"monthly": None})
    assert client.get("/api/summary", params={"month": current}).json()["budgets"] == {}


def test_transactions_hide_own_account_moves_by_default(client, current):
    default = client.get("/api/transactions", params={"month": current}).json()
    only = client.get("/api/transactions", params={"month": current, "internal": "only"}).json()
    assert default and all(t["direction"] != "internal" for t in default)
    assert only and all(t["direction"] == "internal" for t in only)
    assert client.get("/api/transactions", params={"internal": "bogus"}).status_code == 400


def test_create_and_delete_category(client):
    r = client.post("/api/categories", json={"name": "Gifts", "color": "magenta"})
    assert r.status_code == 200 and r.json()["key"] == "gifts"
    assert any(c["key"] == "gifts" and c["custom"] for c in client.get("/api/meta").json()["categories"])
    assert client.post("/api/categories", json={"name": "Gifts"}).status_code == 400
    assert client.post("/api/categories", json={"name": "X", "color": "plaid"}).status_code == 400
    assert client.delete("/api/categories/gifts").status_code == 200
    assert client.delete("/api/categories/dining").status_code == 404
