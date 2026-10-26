"""Setup flow, settings, demo area, import, sync and merchant logos."""
import importlib
import json
import re
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from inbox_ledger import demo, logos, settings
from inbox_ledger.config import DEFAULTS
from inbox_ledger.logos import Brand, Brands

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (180).to_bytes(4, "big") * 2 + b"\x08\x02\x00\x00\x00" + b"\x00" * 32


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A fresh API over an empty data dir."""
    monkeypatch.setenv("INBOX_LEDGER_DATA", str(tmp_path))
    from inbox_ledger import api
    api = importlib.reload(api)
    yield api, TestClient(api.app), tmp_path
    api._close_demo()
    api.store.db.close()


def jsonl(n: int = 40) -> bytes:
    return "".join(json.dumps(m.__dict__) + "\n" for m in demo.generate(months=2, seed=5)[:n]).encode()


# ---- brands --------------------------------------------------------------------

def test_brands_yaml_is_complete():
    spec = yaml.safe_load((DEFAULTS / "brands.yaml").read_text())["brands"]
    assert len(spec) >= 80
    keys = [b["key"] for b in spec]
    assert len(keys) == len(set(keys))
    for b in spec:
        assert re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}", b["domain"]), b
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", b["color"]), b
        assert b["match"] and b["name"]


def test_brand_matching():
    brands = Brands.load(DEFAULTS / "brands.yaml")
    expect = {"careem food": "careem", "amazon.ae": "amazon", "noon.com": "noon", "apple.com/bill": "apple",
              "openai chatgpt subscr": "openai", "carrefour moe": "carrefour", "h&m": "hm", "du": "du",
              "vox cinemas": "vox", "starbucks": "starbucks", "% arabica": "arabica", "life pharmacy": "life-pharmacy"}
    assert {k: getattr(brands.find(k), "key", None) for k in expect} == expect
    assert brands.find("dubai duty free") is None  # "=du" only matches the whole name
    assert brands.find("golden sands") is None and brands.find("") is None


def test_user_brands_override(tmp_path):
    (tmp_path / "brands.yaml").write_text("brands:\n  - {key: zen, name: Zen Corner, domain: zen.example, "
                                          "color: '#123456', match: [zen corner]}\n")
    brands = Brands.load(DEFAULTS / "brands.yaml", tmp_path / "brands.yaml")
    assert brands.find("zen corner").domain == "zen.example"
    assert brands.find("starbucks").key == "starbucks"


# ---- logo fetching -------------------------------------------------------------

def test_fetch_icon_prefers_touch_icon_and_caches(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, limit, timeout=4):
        calls.append(url)
        if url == "https://brand.example/":
            return b'<link rel="icon" href="/f.ico"><link rel="apple-touch-icon" href="/touch.png">', url
        if url.endswith("/touch.png"):
            return PNG, url
        raise OSError("404")

    monkeypatch.setattr(logos, "_get", fake_get)
    b = Brand("brand", "Brand", "brand.example")
    path = logos.fetch_icon(b, tmp_path)
    assert path == tmp_path / "brand.png" and path.read_bytes() == PNG
    assert calls[:2] == ["https://brand.example/", "https://brand.example/touch.png"]
    calls.clear()
    assert logos.fetch_icon(b, tmp_path) == path and not calls  # served from cache


def test_fetch_icon_caches_misses(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(logos, "_get", lambda url, limit, timeout=4: calls.append(url) or (b"<html>nope</html>", url))
    b = Brand("nothing", "Nothing", "nothing.example")
    assert logos.fetch_icon(b, tmp_path) is None
    assert (tmp_path / "nothing.miss").is_file()
    n = len(calls)
    assert logos.fetch_icon(b, tmp_path) is None and len(calls) == n


def test_get_refuses_non_https_and_ip_hosts():
    for url in ("http://brand.example/", "https://127.0.0.1/x.png", "https://[::1]/x.png"):
        with pytest.raises(ValueError):
            logos._get(url, 100)


def test_sniff():
    assert logos.sniff(PNG) == "png"
    assert logos.sniff(b"\x00\x00\x01\x00\x01\x00") == "ico"
    assert logos.sniff(b"  <svg xmlns='http://www.w3.org/2000/svg'/>") == "svg"
    assert logos.sniff(b"<!doctype html>") is None


# ---- settings --------------------------------------------------------------------

def test_settings_defaults_and_validation(tmp_path):
    assert settings.load(tmp_path) == settings.DEFAULTS
    out = settings.save(tmp_path, {"theme": "dark", "logos": 1})
    assert out["theme"] == "dark" and out["logos"] is True
    assert json.loads((tmp_path / "settings.json").read_text())["theme"] == "dark"
    with pytest.raises(ValueError):
        settings.save(tmp_path, {"theme": "sepia"})
    with pytest.raises(ValueError):
        settings.save(tmp_path, {"colour": "red"})
    (tmp_path / "settings.json").write_text("{not json")
    assert settings.load(tmp_path)["theme"] == "system"


def test_settings_api(app):
    api, client, d = app
    s = client.get("/api/settings").json()
    assert s["theme"] == "system" and s["logos"] is False and s["logos_enabled"] is False
    assert s["data_dir"] == str(d) and s["gmail"] == {"credentials": False, "connected": False, "last_email": None,
                                                     "sync": {"state": "idle"}}
    r = client.patch("/api/settings", json={"theme": "light", "currency": "after", "banks": ["Mashreq"]})
    assert r.status_code == 200 and r.json()["theme"] == "light"
    assert client.get("/api/meta").json()["settings"]["currency"] == "after"
    assert client.patch("/api/settings", json={"theme": "neon"}).status_code == 400
    assert client.patch("/api/settings", json={"mode": "demo"}).json()["mode"] == "real"  # only via /api/demo


def test_first_run_meta(app):
    api, client, d = app
    meta = client.get("/api/meta").json()
    assert meta["months"] == [] and meta["source"]["emails"] == 0 and meta["mode"] == "real"
    assert meta["settings"]["onboarded"] is False
    names = [b["name"] for b in meta["bank_profiles"]]
    assert {"Mashreq", "Emirates NBD", "ADCB"} <= set(names)


# ---- import ----------------------------------------------------------------------

def test_import_jsonl(app):
    api, client, d = app
    r = client.post("/api/import", params={"filename": "alerts.jsonl"}, content=jsonl(40))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["read"] == 40 and body["added"] == 40 and body["transactions"] > 0
    assert client.get("/api/meta").json()["source"]["emails"] == 40
    again = client.post("/api/import", params={"filename": "alerts.jsonl"}, content=jsonl(40)).json()
    assert again["added"] == 0  # idempotent


def test_import_rejects_bad_files(app):
    api, client, d = app
    assert client.post("/api/import", params={"filename": "a.jsonl"}, content=b"").status_code == 400
    assert client.post("/api/import", params={"filename": "a.pdf"}, content=b"%PDF").status_code == 400
    assert client.post("/api/import", params={"filename": "a.jsonl"}, content=b'{"id": 1}\n').status_code == 400
    assert client.post("/api/import", params={"filename": "a.mbox"}, content=b"hello").status_code == 400


# ---- demo area -------------------------------------------------------------------

def test_demo_area_is_isolated(app):
    api, client, d = app
    client.post("/api/import", params={"filename": "mine.jsonl"}, content=jsonl(10))
    real_emails = client.get("/api/meta").json()["source"]["emails"]

    r = client.post("/api/demo")
    assert r.status_code == 200 and r.json()["mode"] == "demo" and r.json()["emails"] > 200
    meta = client.get("/api/meta").json()
    assert meta["mode"] == "demo" and meta["source"]["demo"] and len(meta["months"]) >= 5
    assert (d / "demo" / "ledger.db").is_file() and (d / "demo" / "DEMO").is_file()
    assert api.store.source()["emails"] == real_emails  # nothing leaked into the real ledger
    assert client.get("/api/settings").json()["logos_enabled"] is True  # logos default on in the demo

    # Corrections in the demo stay in the demo.
    tx = client.get("/api/transactions", params={"q": "Zen Corner"}).json()[0]
    client.patch(f"/api/transactions/{tx['id']}", json={"category": "health"})
    assert any(r["merchant_key"] == "zen corner" for r in client.get("/api/rules").json())

    r = client.delete("/api/demo")
    assert r.status_code == 200 and r.json()["mode"] == "real"
    meta = client.get("/api/meta").json()
    assert meta["mode"] == "real" and not meta["source"]["demo"] and meta["source"]["emails"] == real_emails
    assert client.get("/api/rules").json() == []
    assert not (d / "demo").exists()


def test_import_leaves_the_demo(app):
    api, client, d = app
    client.post("/api/demo")
    client.post("/api/import", params={"filename": "mine.jsonl"}, content=jsonl(5))
    meta = client.get("/api/meta").json()
    assert meta["mode"] == "real" and meta["source"]["emails"] == 5


# ---- Gmail -----------------------------------------------------------------------

def test_sync_needs_credentials(app):
    api, client, d = app
    r = client.post("/api/sync")
    assert r.status_code == 400 and "credentials.json" in r.json()["detail"]


def test_credentials_upload(app):
    api, client, d = app
    assert client.post("/api/gmail/credentials", content=b"nope").status_code == 400
    assert client.post("/api/gmail/credentials", content=b'{"foo": 1}').status_code == 400
    good = json.dumps({"installed": {"client_id": "x.apps.googleusercontent.com", "client_secret": "s"}})
    assert client.post("/api/gmail/credentials", content=good.encode()).json() == {"ok": True}
    assert (d / "credentials.json").read_text() == good
    assert client.get("/api/settings").json()["gmail"]["credentials"] is True


def test_sync_runs_in_background(app, monkeypatch):
    api, client, d = app
    (d / "credentials.json").write_text("{}")
    seen = {}

    def fake_sync(st, data=None, full=False, limit=2000, only=None, progress=lambda **kw: None):
        progress(step="fetching", message="Reading Mashreq emails…")
        added = st.add_messages(demo.generate(months=1, seed=2)[:12])
        seen["only"] = only
        return {"fetched": {"Mashreq": 12}, "added": added, **st.rebuild()}

    monkeypatch.setattr(api, "_run_sync", fake_sync)
    client.patch("/api/settings", json={"banks": ["Mashreq"]})
    assert client.post("/api/sync").json()["state"] == "running"
    for _ in range(100):
        s = client.get("/api/sync").json()
        if s["state"] != "running":
            break
        time.sleep(0.05)
    assert s["state"] == "done", s
    assert s["result"]["added"] == 12 and s["message"] == "12 new emails"
    assert seen["only"] == ["Mashreq"]
    assert client.get("/api/meta").json()["source"]["emails"] == 12


def test_sync_reports_errors(app, monkeypatch):
    api, client, d = app
    (d / "credentials.json").write_text("{}")

    def boom(*a, **kw):
        raise RuntimeError("access_denied")

    monkeypatch.setattr(api, "_run_sync", boom)
    client.post("/api/sync")
    for _ in range(100):
        s = client.get("/api/sync").json()
        if s["state"] != "running":
            break
        time.sleep(0.05)
    assert s == {**s, "state": "error", "message": "access_denied"}


# ---- logos endpoint ----------------------------------------------------------------

def test_logo_endpoint_disabled_by_default(app, monkeypatch):
    api, client, d = app
    fetched = []
    monkeypatch.setattr(api, "fetch_icon", lambda b, cache: fetched.append(b.key))
    r = client.get("/api/logo/starbucks")
    assert r.status_code == 404 and "turned off" in r.json()["detail"]
    assert not fetched and not (d / "logos").exists()


def test_logo_endpoint_when_enabled(app, monkeypatch):
    api, client, d = app

    def fake_fetch(brand, cache):
        cache.mkdir(parents=True, exist_ok=True)
        (cache / f"{brand.key}.png").write_bytes(PNG)
        return cache / f"{brand.key}.png"

    monkeypatch.setattr(api, "fetch_icon", fake_fetch)
    client.patch("/api/settings", json={"logos": True})
    r = client.get("/api/logo/starbucks dubai")  # any merchant key that maps to a brand
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    assert "sandbox" in r.headers["content-security-policy"]
    assert (d / "logos" / "starbucks.png").is_file()
    assert client.get("/api/logo/golden sands").status_code == 404
    client.patch("/api/settings", json={"logos": False})  # turning logos off forgets them
    assert not (d / "logos").exists()


def test_transactions_carry_brand(app):
    api, client, d = app
    client.post("/api/import", params={"filename": "a.jsonl"}, content=jsonl(80))
    txs = client.get("/api/transactions", params={"internal": "show"}).json()
    branded = {t["merchant_key"]: t["brand"] for t in txs if t["brand"]}
    assert branded and all({"key", "name", "color"} == set(b) for b in branded.values())
    assert all(t["brand"] is None for t in txs if t["kind"] == "transfer")
    month = client.get("/api/meta").json()["current"]
    s = client.get("/api/summary", params={"month": month}).json()
    assert all("brand" in m for m in s["top_merchants"])


def test_logo_fetcher_refuses_private_and_plain_http_hosts():
    import pytest
    from inbox_ledger.logos import _check_public
    for url in ("http://example.com/favicon.ico", "https://127.0.0.1/x", "https://localhost/x", "https://[::1]/x"):
        with pytest.raises(ValueError):
            _check_public(url)


# ---- dashboard front-end (served files) -------------------------------------------

WEB = Path(__file__).resolve().parents[1] / "inbox_ledger" / "web"


def test_definitions_script_is_served_before_the_sections(app):
    api, client, d = app
    html = client.get("/").text
    scripts = re.findall(r'<script src="([^"]+)"', html)
    assert scripts.index("shared.js") < scripts.index("defs.js") < scripts.index("overview.js")
    js = client.get("/defs.js").text
    for key in ("spent", "came_in", "saved", "left", "fixed", "everyday", "settled", "hidden", "needs_review"):
        assert re.search(rf"^\s*{key}: \{{ title:", js, re.M), key
    assert "function defHelp(" in js and '"/api/definitions"' in js


def test_activity_chips_use_the_owners_words():
    js = (WEB / "activity.js").read_text()
    for name in ("Needs review", "Between my accounts", "Settled (cancelled out)", "Hidden (didn’t happen)", "Sent to people"):
        assert name in js, name
    assert "Show hidden" not in js and "Transfers to people" not in js
