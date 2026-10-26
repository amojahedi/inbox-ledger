"""HTTP API and static dashboard. Binds to localhost by default — it is your money."""
import json
import os
import shutil
import tempfile
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, settings
from .config import DEFAULTS, data_dir, open_store
from .logos import MEDIA, Brands, fetch_icon
from .parsing import load_banks
from .paylater import load_providers
from .store import Categories, Store
from .sync import run_sync as _run_sync

WEB = Path(__file__).parent / "web"
DIRECTIONS = {"out", "in", "internal"}

app = FastAPI(title="Inbox Ledger", docs_url="/api/docs", openapi_url="/api/openapi.json")
store = open_store()  # your real ledger
brands = Brands.load(DEFAULTS / "brands.yaml", data_dir() / "brands.yaml")

# Blocks DNS-rebinding: a web page can't reach this API through a hostname it controls.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver",
                   *filter(None, os.environ.get("INBOX_LEDGER_HOSTS", "").split(","))])


# ---- which ledger: your own, or the demo area ---------------------------------
#
# The demo lives in <data dir>/demo/ with its own database, so example rows can never
# mix with real ones. settings.json's "mode" picks which one the dashboard shows.

_demo: Optional[Store] = None
_demo_lock = threading.Lock()


def demo_dir() -> Path:
    return data_dir() / "demo"


def _open_demo() -> Store:
    global _demo
    if _demo is None:
        d, root = demo_dir(), data_dir()
        _demo = Store(d / "ledger.db", load_banks(DEFAULTS / "banks", root / "banks"),
                      Categories.load(DEFAULTS / "categories.yaml", root / "categories.yaml"),
                      load_providers(DEFAULTS / "paylater", root / "paylater"))
    return _demo


def _close_demo() -> None:
    global _demo
    if _demo is not None:
        _demo.db.close()
        _demo = None


def prefs() -> dict:
    return settings.load(data_dir())


def in_demo(p: Optional[dict] = None) -> bool:
    """True when the dashboard shows the separate demo area (not a data dir made with `demo`)."""
    return (p or prefs())["mode"] == "demo" and (demo_dir() / "ledger.db").is_file()


def S() -> Store:
    """The ledger the dashboard is looking at right now."""
    return _open_demo() if in_demo() else store


def logos_key(p: Optional[dict] = None) -> str:
    """Which switch controls logos right now: example data (demo area or a `demo` data dir) or your own."""
    return "demo_logos" if in_demo(p) or (data_dir() / "DEMO").exists() else "logos"


def logos_on(p: Optional[dict] = None) -> bool:
    p = p or prefs()
    return p[logos_key(p)]


def logo_dir() -> Path:
    return (demo_dir() if in_demo() else data_dir()) / "logos"


def _brand(merchant: str, kind: str = "") -> Optional[dict]:
    if kind == "transfer":  # people, not shops
        return None
    b = brands.find(merchant)
    return b.public() if b else None


# ---- models -------------------------------------------------------------------

class Correction(BaseModel):
    category: Optional[str] = None
    direction: Optional[str] = None
    note: Optional[str] = None
    remember: bool = True
    match_amount: bool = False


class NewCategory(BaseModel):
    name: str
    color: str = "gray"


COLORS = {"blue", "orange", "aqua", "yellow", "magenta", "green", "violet", "red", "brown", "teal", "cyan",
          "navy", "plum", "olive", "slate", "forest", "tan", "gray"}


class Budget(BaseModel):
    monthly: Optional[float] = None


# ---- ledger -------------------------------------------------------------------

@app.get("/api/meta")
def meta():
    st, p = S(), prefs()
    months = st.months()
    demo = in_demo(p)
    return {
        "currency": st.categories.base_currency,
        "categories": [{"key": c["key"], "name": c["name"], "color": c["color"], "custom": bool(c.get("custom"))}
                       for c in st.categories.items],
        "months": months,
        "current": months[-1]["month"] if months else date.today().isoformat()[:7],
        "banks": [b.name for b in st.banks],
        "bank_profiles": [{"name": b.name, "country": getattr(b, "country", "") or "",
                           "gmail": bool(b.gmail_query)} for b in st.banks],
        "pay_later": [p_.name for p_ in st.providers],
        "mode": "demo" if demo else "real",
        "source": {"demo": demo or (data_dir() / "DEMO").exists(), **st.source()},
        "settings": {k: p[k] for k in ("theme", "currency", "number", "banks", "onboarded")},
        "logos": logos_on(p),
    }


@app.get("/api/summary")
def summary(month: str):
    s = S().summary(month)
    for m in s.get("top_merchants", []):
        m["brand"] = _brand(m["merchant"])
    return s


@app.get("/api/category/{key}")
def category_detail(key: str, month: str):
    d = S().category_detail(month, key)
    for p in d["places"]:
        p["brand"] = _brand(p["merchant"])
    return d


@app.get("/api/trends")
def trends(month: str, months: int = 12):
    return S().trends(month, max(1, min(months, 36)))


@app.get("/api/transactions")
def transactions(month: Optional[str] = None, category: Optional[str] = None, q: Optional[str] = None,
                 internal: str = "hide", via: Optional[str] = None):
    if internal not in ("hide", "only", "show"):
        raise HTTPException(400, "internal must be hide, only or show")
    rows = S().transactions(month=month, category=category, q=q, internal=internal, via=via)
    for t in rows:
        t["brand"] = _brand(t["merchant_key"], t["kind"])
    return rows


@app.patch("/api/transactions/{tx_id}")
def correct(tx_id: str, body: Correction):
    st = S()
    if body.category and body.category not in st.categories.by_key:
        raise HTTPException(400, "unknown category")
    if body.direction and body.direction not in DIRECTIONS:
        raise HTTPException(400, "direction must be out, in or internal")
    try:
        st.correct(tx_id, body.category, body.direction, body.note, body.remember, body.match_amount)
    except KeyError:
        raise HTTPException(404, "transaction not found")
    return {"ok": True}


@app.post("/api/categories")
def add_category(body: NewCategory):
    if body.color not in COLORS:
        raise HTTPException(400, f"color must be one of {sorted(COLORS)}")
    try:
        c = S().add_category(body.name, body.color)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"key": c["key"], "name": c["name"], "color": c["color"], "custom": True}


@app.delete("/api/categories/{key}")
def delete_category(key: str):
    try:
        S().delete_category(key)
    except KeyError:
        raise HTTPException(404, "not a custom category")
    return {"ok": True}


@app.get("/api/rules")
def rules():
    return S().rules()


@app.delete("/api/rules/{key:path}")
def delete_rule(key: str, amount: float = 0):
    S().delete_rule(key, amount)
    return {"ok": True}


@app.put("/api/budgets/{category}")
def set_budget(category: str, body: Budget):
    st = S()
    if category not in st.categories.by_key:
        raise HTTPException(400, "unknown category")
    st.set_budget(category, body.monthly)
    return {"ok": True}


# ---- settings -----------------------------------------------------------------

def _gmail_status() -> dict:
    d = data_dir()
    return {"credentials": (d / "credentials.json").is_file(), "connected": (d / "token.json").is_file(),
            "last_email": store.source()["last"], "sync": dict(_sync)}


@app.get("/api/settings")
def get_settings():
    p = prefs()
    return {**p, "logos_enabled": logos_on(p), "logos_key": logos_key(p), "demo": in_demo(p), "demo_dir": (data_dir() / "DEMO").exists(),
            "data_dir": str(data_dir()), "version": __version__, "gmail": _gmail_status(),
            "banks_available": [b.name for b in store.banks], "pay_later": [x.name for x in store.providers],
            "emails": store.source()["emails"]}


@app.patch("/api/settings")
def patch_settings(body: dict):
    body = {k: v for k, v in body.items() if k != "mode"}  # use /api/demo to switch ledgers
    try:
        before = prefs()
        after = settings.save(data_dir(), body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if before["logos"] and not after["logos"]:
        # Turning logos off also forgets which brands were looked up.
        shutil.rmtree(data_dir() / "logos", ignore_errors=True)
    return get_settings()


# ---- demo area ----------------------------------------------------------------


@app.post("/api/demo")
def enter_demo():
    """Open the demo: synthetic data in <data dir>/demo/, never mixed with your own."""
    from .demo import seed
    with _demo_lock:
        st = _open_demo()
        if not st.source()["emails"]:
            (demo_dir() / "DEMO").write_text("Synthetic data for Ledger's demo. Safe to delete.\n")
            seed(st)
        settings.save(data_dir(), {"mode": "demo"})
    return {"mode": "demo", **st.source()}


@app.delete("/api/demo")
def leave_demo():
    """Back to your own ledger. The demo area is deleted; it is rebuilt fresh next time."""
    with _demo_lock:
        settings.save(data_dir(), {"mode": "real"})
        _close_demo()
        shutil.rmtree(demo_dir(), ignore_errors=True)
    return {"mode": "real", **store.source()}


# ---- bringing in email --------------------------------------------------------

def _use_real_ledger() -> None:
    if prefs()["mode"] != "real":
        settings.save(data_dir(), {"mode": "real"})


@app.post("/api/import")
async def import_file(request: Request, filename: str = "upload.jsonl"):
    """Import a Google Takeout .mbox or a .jsonl of emails. The file is the raw request body."""
    from .sources import read_jsonl, read_mbox
    suffix = Path(filename).suffix.lower()
    if suffix not in (".mbox", ".jsonl", ".json", ".txt", ".eml", ""):
        raise HTTPException(400, "Choose a .mbox file (Google Takeout) or a .jsonl file.")
    fd, tmp = tempfile.mkstemp(prefix="ledger-import-", suffix=suffix or ".mbox")
    try:
        size = 0
        with os.fdopen(fd, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                f.write(chunk)
        if not size:
            raise HTTPException(400, "That file is empty.")
        path = Path(tmp)
        with open(path, "rb") as f:
            head = f.read(64).lstrip()
        is_json = suffix in (".jsonl", ".json") or head.startswith(b"{")
        try:
            msgs = await run_in_threadpool(lambda: list(read_jsonl(path) if is_json else read_mbox(path)))
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise HTTPException(400, f"Couldn't read that file ({e.__class__.__name__}). "
                                     "Use a .mbox from Google Takeout or a .jsonl with id, date, sender, body.")
        if not msgs:
            raise HTTPException(400, "No emails found in that file.")
        added = store.add_messages(msgs)
        result = await run_in_threadpool(store.rebuild)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    _use_real_ledger()
    return {"read": len(msgs), "added": added, **result, "source": store.source()}


_sync: dict = {"state": "idle"}  # idle | running | done | error
_sync_lock = threading.Lock()




def _sync_worker(full: bool) -> None:
    def progress(**kw):
        _sync.update(kw)
    try:
        st = open_store()  # its own connection: this runs on a background thread
        try:
            result = _run_sync(st, data_dir(), full=full, only=prefs()["banks"] or None, progress=progress)
        finally:
            st.db.close()
        _sync.update(state="done", step="done", result=result, finished=datetime.now().isoformat(timespec="seconds"),
                     message=f"{result['added']} new email{'' if result['added'] == 1 else 's'}")
        _use_real_ledger()
    except Exception as e:  # surfaced to the UI, which explains what to do
        _sync.update(state="error", step="error", message=str(e) or e.__class__.__name__)


@app.post("/api/sync")
def start_sync(full: bool = False):
    """Start a Gmail sync in the background; poll GET /api/sync for progress."""
    if not (data_dir() / "credentials.json").is_file():
        raise HTTPException(400, "Add your Google OAuth client file (credentials.json) first.")
    with _sync_lock:
        if _sync.get("state") == "running":
            return dict(_sync)
        _sync.clear()
        _sync.update(state="running", step="starting", message="Connecting to Gmail…",
                     started=datetime.now().isoformat(timespec="seconds"))
        threading.Thread(target=_sync_worker, args=(full,), daemon=True).start()
    return dict(_sync)


@app.get("/api/sync")
def sync_status():
    return dict(_sync)


@app.post("/api/gmail/credentials")
async def save_credentials(request: Request):
    """Store the OAuth client JSON downloaded from Google Cloud Console as <data dir>/credentials.json."""
    raw = await request.body()
    try:
        spec = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "That isn't a JSON file. Download the OAuth client JSON from Google Cloud.")
    client = spec.get("installed") or spec.get("web") if isinstance(spec, dict) else None
    if not isinstance(client, dict) or not client.get("client_id"):
        raise HTTPException(400, "That JSON isn't an OAuth client. Create a “Desktop app” OAuth client ID.")
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / "credentials.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    return {"ok": True}


# ---- merchant logos -----------------------------------------------------------

@app.get("/api/logo/{merchant_key:path}")
def logo(merchant_key: str):
    """A merchant's brand icon, fetched once from the brand's own website and cached. Off unless enabled."""
    if not logos_on():
        raise HTTPException(404, "Merchant logos are turned off in Settings.")
    b = brands.find(merchant_key)
    if not b:
        raise HTTPException(404, "unknown brand")
    path = fetch_icon(b, logo_dir())
    if not path:
        raise HTTPException(404, "no logo")
    return FileResponse(path, media_type=MEDIA[path.suffix[1:]], headers={
        "Cache-Control": "private, max-age=604800",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    })


# ---- dashboard ----------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
