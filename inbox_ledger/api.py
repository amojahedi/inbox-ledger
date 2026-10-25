"""HTTP API and static dashboard. Binds to localhost by default — it is your money."""
import os
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import data_dir, open_store

WEB = Path(__file__).parent / "web"
DIRECTIONS = {"out", "in", "internal"}

app = FastAPI(title="Inbox Ledger", docs_url="/api/docs", openapi_url="/api/openapi.json")
store = open_store()

# Blocks DNS-rebinding: a web page can't reach this API through a hostname it controls.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver",
                   *filter(None, os.environ.get("INBOX_LEDGER_HOSTS", "").split(","))])


class Correction(BaseModel):
    category: Optional[str] = None
    direction: Optional[str] = None
    note: Optional[str] = None
    remember: bool = True
    match_amount: bool = False


class NewCategory(BaseModel):
    name: str
    color: str = "gray"


COLORS = {"blue", "orange", "aqua", "yellow", "magenta", "green", "violet", "red", "gray"}


class Budget(BaseModel):
    monthly: Optional[float] = None


@app.get("/api/meta")
def meta():
    months = store.months()
    return {
        "currency": store.categories.base_currency,
        "categories": [{"key": c["key"], "name": c["name"], "color": c["color"], "custom": bool(c.get("custom"))}
                       for c in store.categories.items],
        "months": months,
        "current": months[-1]["month"] if months else date.today().isoformat()[:7],
        "banks": [b.name for b in store.banks],
        "source": {"demo": (data_dir() / "DEMO").exists(), **store.source()},
    }


@app.get("/api/summary")
def summary(month: str):
    return store.summary(month)


@app.get("/api/transactions")
def transactions(month: Optional[str] = None, category: Optional[str] = None, q: Optional[str] = None,
                 internal: str = "hide"):
    if internal not in ("hide", "only", "show"):
        raise HTTPException(400, "internal must be hide, only or show")
    return store.transactions(month=month, category=category, q=q, internal=internal)


@app.patch("/api/transactions/{tx_id}")
def correct(tx_id: str, body: Correction):
    if body.category and body.category not in store.categories.by_key:
        raise HTTPException(400, "unknown category")
    if body.direction and body.direction not in DIRECTIONS:
        raise HTTPException(400, "direction must be out, in or internal")
    try:
        store.correct(tx_id, body.category, body.direction, body.note, body.remember, body.match_amount)
    except KeyError:
        raise HTTPException(404, "transaction not found")
    return {"ok": True}


@app.post("/api/categories")
def add_category(body: NewCategory):
    if body.color not in COLORS:
        raise HTTPException(400, f"color must be one of {sorted(COLORS)}")
    try:
        c = store.add_category(body.name, body.color)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"key": c["key"], "name": c["name"], "color": c["color"], "custom": True}


@app.delete("/api/categories/{key}")
def delete_category(key: str):
    try:
        store.delete_category(key)
    except KeyError:
        raise HTTPException(404, "not a custom category")
    return {"ok": True}


@app.get("/api/rules")
def rules():
    return store.rules()


@app.delete("/api/rules/{key:path}")
def delete_rule(key: str, amount: float = 0):
    store.delete_rule(key, amount)
    return {"ok": True}


@app.put("/api/budgets/{category}")
def set_budget(category: str, body: Budget):
    if category not in store.categories.by_key:
        raise HTTPException(400, "unknown category")
    store.set_budget(category, body.monthly)
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
