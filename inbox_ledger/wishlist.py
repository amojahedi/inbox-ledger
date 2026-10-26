"""The wishlist: things you want to buy, and when your real saving pace says you can have them.

Wishes live in their own tables on the ledger's SQLite connection, so the demo area and your own
ledger each keep their own list. Nothing here creates or changes a transaction.

How the prediction works
------------------------
* Saving pace = what you keep a month: the average of (came in − spent) over the last three *complete*
  months that had income (fewer if that is all there is). It is shown as its two parts, saved (net moves
  to your own savings, `summary.moved`) + left (`summary.left`), so it never reads as more savings than
  the Overview shows. With no income at all, the user can type their own monthly figure instead.
* "Already saved" is money set aside for wishes today. It covers wishes in priority order.
* Wishes are funded cumulatively in priority order: wish k is ready once
  saved + pace × months ≥ price₁ + … + priceₖ.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS wishes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, price REAL NOT NULL,
  link TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', target TEXT,
  position INTEGER NOT NULL DEFAULT 0, created_at TEXT, bought_at TEXT,
  paid_from_saved REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS wishlist_settings (key TEXT PRIMARY KEY, value TEXT);
"""

DAYS_PER_MONTH = 365.25 / 12
PACE_MONTHS = 3
TIP_SHARE = 0.20  # "spend 20% less on …"
# Spending people can usually trim. Rent, bills, groceries and health stay out of the advice.
DISCRETIONARY = ("dining", "coffee", "shopping", "entertainment", "taxi")
SETTINGS = {"saved": 0.0, "manual_pace": None, "use_manual": False}
MAX_PRICE = 1e9


def ensure(db: sqlite3.Connection) -> None:
    """Create the tables on first use. A plain read otherwise: executescript() would commit."""
    have = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('wishes', 'wishlist_settings')")}
    if len(have) < 2:
        db.executescript(SCHEMA)


# ---- settings -------------------------------------------------------------------

def get_settings(db: sqlite3.Connection) -> dict:
    ensure(db)
    out = dict(SETTINGS)
    for r in db.execute("SELECT key, value FROM wishlist_settings"):
        if r[0] in out:
            out[r[0]] = json.loads(r[1])
    return out


def save_settings(db: sqlite3.Connection, changes: dict) -> dict:
    unknown = set(changes) - set(SETTINGS)
    if unknown:
        raise ValueError(f"unknown setting: {', '.join(sorted(unknown))}")
    clean: dict[str, Any] = {}
    if "saved" in changes:
        clean["saved"] = _amount(changes["saved"] or 0, "saved", allow_zero=True)
    if "manual_pace" in changes:
        v = changes["manual_pace"]
        clean["manual_pace"] = None if v is None or v == "" else _number(v, "manual_pace")
        if clean["manual_pace"] is not None and abs(clean["manual_pace"]) > MAX_PRICE:
            raise ValueError("manual_pace is too large")
    if "use_manual" in changes:
        clean["use_manual"] = bool(changes["use_manual"])
    ensure(db)
    with db:
        db.executemany("INSERT OR REPLACE INTO wishlist_settings VALUES (?,?)",
                       [(k, json.dumps(v)) for k, v in clean.items()])
    return get_settings(db)


# ---- wishes ---------------------------------------------------------------------

def _number(v: Any, field: str) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number")
    if n != n or n in (float("inf"), float("-inf")):
        raise ValueError(f"{field} must be a number")
    return round(n, 2)


def _amount(v: Any, field: str = "price", allow_zero: bool = False) -> float:
    n = _number(v, field)
    if n < 0 or (n == 0 and not allow_zero):
        raise ValueError(f"{field} must be more than zero")
    if n > MAX_PRICE:
        raise ValueError(f"{field} is too large")
    return n


def clean_link(link: Optional[str]) -> str:
    """Only plain web links: "apple.com/airpods" becomes https://apple.com/airpods; anything else is refused."""
    link = (link or "").strip()
    if not link:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", link, re.I):
        if re.match(r"^[a-z][a-z0-9+.-]*:", link, re.I) and not re.match(r"^[^:/]+:\d", link):
            raise ValueError("link must be a web address (https://…)")
        link = "https://" + link
    if not re.match(r"^https?://[^\s/?#]+\.[^\s/?#]+", link, re.I) or re.search(r"\s", link):
        raise ValueError("link must be a web address (https://…)")
    return link[:500]


def _target(v: Optional[str]) -> Optional[str]:
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        raise ValueError("target must be a date like 2027-03-01")


def _fields(data: dict, partial: bool) -> dict:
    out: dict[str, Any] = {}
    if "name" in data or not partial:
        name = re.sub(r"\s+", " ", str(data.get("name") or "")).strip()
        if not name:
            raise ValueError("name is required")
        out["name"] = name[:80]
    if "price" in data or not partial:
        out["price"] = _amount(data.get("price"))
    if "link" in data:
        out["link"] = clean_link(data["link"])
    if "note" in data:
        out["note"] = re.sub(r"\s+", " ", str(data["note"] or "")).strip()[:280]
    if "target" in data:
        out["target"] = _target(data["target"])
    return out


def _rows(db: sqlite3.Connection, sql: str, args: tuple = ()) -> sqlite3.Cursor:
    cur = db.cursor()
    cur.row_factory = sqlite3.Row  # per cursor: the connection is shared with the rest of the app
    return cur.execute(sql, args)


def _row(r: sqlite3.Row) -> dict:
    return {k: r[k] for k in ("id", "name", "price", "link", "note", "target", "position", "created_at",
                              "bought_at", "paid_from_saved")}


def wishes(db: sqlite3.Connection, bought: bool = False) -> list[dict]:
    ensure(db)
    if bought:
        sql = "SELECT * FROM wishes WHERE bought_at IS NOT NULL ORDER BY bought_at DESC, id DESC"
    else:
        sql = "SELECT * FROM wishes WHERE bought_at IS NULL ORDER BY position, id"
    return [_row(r) for r in _rows(db, sql)]


def get(db: sqlite3.Connection, wish_id: int) -> dict:
    ensure(db)
    r = _rows(db, "SELECT * FROM wishes WHERE id=?", (wish_id,)).fetchone()
    if not r:
        raise KeyError(wish_id)
    return _row(r)


def add(db: sqlite3.Connection, data: dict) -> dict:
    f = _fields(data, partial=False)
    ensure(db)
    with db:
        last = db.execute("SELECT coalesce(max(position), -1) FROM wishes WHERE bought_at IS NULL").fetchone()[0]
        cur = db.execute(
            "INSERT INTO wishes (name, price, link, note, target, position, created_at) VALUES (?,?,?,?,?,?,?)",
            (f["name"], f["price"], f.get("link", ""), f.get("note", ""), f.get("target"), last + 1,
             datetime.now().isoformat(timespec="seconds")))
    return get(db, cur.lastrowid)


def update(db: sqlite3.Connection, wish_id: int, data: dict) -> dict:
    get(db, wish_id)
    f = _fields(data, partial=True)
    if f:
        with db:
            db.execute(f"UPDATE wishes SET {', '.join(f'{k}=?' for k in f)} WHERE id=?", (*f.values(), wish_id))
    return get(db, wish_id)


def delete(db: sqlite3.Connection, wish_id: int) -> None:
    get(db, wish_id)
    with db:
        db.execute("DELETE FROM wishes WHERE id=?", (wish_id,))


def reorder(db: sqlite3.Connection, ids: list[int]) -> None:
    """Set the priority order. `ids` must name every wish still on the list, each once."""
    current = [w["id"] for w in wishes(db)]
    if sorted(ids) != sorted(current):
        raise ValueError("order must list every wish on the list exactly once")
    with db:
        db.executemany("UPDATE wishes SET position=? WHERE id=?", [(i, wid) for i, wid in enumerate(ids)])


def set_bought(db: sqlite3.Connection, wish_id: int, bought: bool = True) -> dict:
    """Move a wish to the Bought list (or back). The share of "already saved" that was covering it is
    taken out of the savings pot, and put back if it returns to the list. No transaction is created."""
    w = get(db, wish_id)
    s = get_settings(db)
    if bought and not w["bought_at"]:
        covered = next((x["covered"] for x in _fund(wishes(db), s["saved"]) if x["id"] == wish_id), 0.0)
        with db:
            db.execute("UPDATE wishes SET bought_at=?, paid_from_saved=? WHERE id=?",
                       (datetime.now().isoformat(timespec="seconds"), covered, wish_id))
        save_settings(db, {"saved": round(s["saved"] - covered, 2)})
    elif not bought and w["bought_at"]:
        with db:
            # Back to the list where it was bought from: at the top, since it was the next thing to buy.
            db.execute("UPDATE wishes SET position = position + 1 WHERE bought_at IS NULL")
            db.execute("UPDATE wishes SET bought_at=NULL, paid_from_saved=0, position=0 WHERE id=?", (wish_id,))
        save_settings(db, {"saved": round(s["saved"] + (w["paid_from_saved"] or 0), 2)})
    return get(db, wish_id)


# ---- saving pace ----------------------------------------------------------------

def _month(d: date) -> str:
    return d.isoformat()[:7]


def saving_pace(store, today: Optional[date] = None) -> dict:
    """Average monthly keep (came in − spent = saved + left) over the last complete months that had income."""
    today = today or date.today()
    current = _month(today)
    months = [m for m in store.months() if m["month"] < current]
    first = store.db.execute("SELECT min(occurred_at) FROM transactions WHERE counted=1").fetchone()[0]
    # The first month of data is only complete if the emails start at the very beginning of it.
    if months and first and first[:7] == months[0]["month"] and int(first[8:10]) > 3 and len(months) > 1:
        months = months[1:]
    used = [m for m in months if (m["received"] or 0) > 0][-PACE_MONTHS:]
    rows = [{"month": m["month"], "in": round(m["received"], 2), "out": round(m["spent"], 2),
             "saved": round(m.get("moved") or 0, 2),
             "left": round(m["received"] - m["spent"] - (m.get("moved") or 0), 2),
             "keep": round(m["received"] - m["spent"], 2)} for m in used]
    if not rows:
        return {"amount": None, "months": [], "avg_in": None, "avg_out": None, "avg_saved": None, "avg_left": None}
    n = len(rows)
    # Whole units, so the sums shown on screen ("30,000 came in − 13,900 spent", "8,000 saved + 8,100 left")
    # always add up to the same figure.
    avg_in = round(sum(r["in"] for r in rows) / n)
    avg_out = round(sum(r["out"] for r in rows) / n)
    avg_saved = round(sum(r["saved"] for r in rows) / n)
    return {"amount": float(avg_in - avg_out), "months": rows, "avg_in": avg_in, "avg_out": avg_out,
            "avg_saved": avg_saved, "avg_left": avg_in - avg_out - avg_saved}


def _categories(store, months: list[str]) -> dict[str, float]:
    if not months:
        return {}
    q = (f"SELECT category, sum(spend) FROM transactions WHERE month IN ({','.join('?' * len(months))})"
         " AND spend!=0 AND counted=1 GROUP BY category")  # same rows and refund netting as the summaries
    return {r[0]: round(r[1] / len(months), 2) for r in store.db.execute(q, months)}


# ---- the plan -------------------------------------------------------------------

def _fund(items: list[dict], saved: float) -> list[dict]:
    """How much of "already saved" covers each wish, in priority order."""
    out, before = [], 0.0
    for w in items:
        covered = round(min(max(saved - before, 0.0), w["price"]), 2)
        out.append({"id": w["id"], "before": round(before, 2), "covered": covered})
        before += w["price"]
    return out


def _when(needed: float, pace: Optional[float], today: date) -> tuple[Optional[float], Optional[str]]:
    """Months until `needed` more is saved at `pace`, and that date. None when it never happens."""
    if needed <= 0:
        return 0.0, today.isoformat()
    if not pace or pace <= 0:
        return None, None
    months = needed / pace
    return round(months, 3), (today + timedelta(days=round(months * DAYS_PER_MONTH))).isoformat()


def plan(store, today: Optional[date] = None) -> dict:
    """Everything the Wishlist tab shows: pace, each wish's ready date, target checks and a tip."""
    today = today or date.today()
    db = store.db
    s = get_settings(db)
    auto = saving_pace(store, today)
    manual = s["manual_pace"]
    if manual is not None and (s["use_manual"] or auto["amount"] is None):
        pace, source = manual, "manual"
    elif auto["amount"] is not None:
        pace, source = auto["amount"], "data"
    else:
        pace, source = None, "none"
    saved = s["saved"]

    items = wishes(db)
    funding = {f["id"]: f for f in _fund(items, saved)}
    out = []
    for w in items:
        f = funding[w["id"]]
        cumulative = round(f["before"] + w["price"], 2)
        needed = round(max(cumulative - saved, 0.0), 2)
        months, ready = _when(needed, pace, today)
        status = "ready" if needed <= 0 else ("never" if months is None else "future")
        item = {**w, "cumulative": cumulative, "before": f["before"], "covered": f["covered"],
                "progress": round(f["covered"] / w["price"], 4), "needed": needed, "status": status,
                "months": months, "ready_date": ready, "target_check": None}
        if w["target"]:
            item["target_check"] = _target_check(w, needed, ready, pace, saved, today, first=not out)
        out.append(item)

    total = round(sum(w["price"] for w in items), 2)
    return {
        "today": today.isoformat(),
        "currency": store.categories.base_currency,
        "saved": saved,
        "total": total,
        "pace": {"amount": pace, "source": source, "auto": auto, "manual": manual, "use_manual": s["use_manual"]},
        "wishes": out,
        "bought": wishes(db, bought=True),
        "tip": _tip(store, out, auto, pace, saved, today),
    }


def _target_check(w: dict, needed: float, ready: Optional[str], pace: Optional[float], saved: float,
                  today: date, first: bool) -> dict:
    target = date.fromisoformat(w["target"])
    days_left = (target - today).days
    months_left = round(days_left / DAYS_PER_MONTH, 3)
    on_track = needed <= 0 or (ready is not None and ready <= w["target"])
    out = {"date": w["target"], "months_left": months_left, "passed": days_left <= 0, "on_track": on_track,
           "needed_per_month": None, "extra_per_month": None, "spare_per_month": None, "top_fixes": False}
    if needed <= 0:
        return out
    if days_left > 0:
        per_month = needed / months_left
        out["needed_per_month"] = round(per_month, 2)
        if on_track:
            out["spare_per_month"] = round((pace or 0) - per_month, 2)
        else:
            out["extra_per_month"] = round(per_month - (pace or 0), 2)
            own = max(w["price"] - saved, 0.0)  # if it were first in line
            out["top_fixes"] = not first and bool(pace and pace > 0) and own / months_left <= pace
    return out


def _tip(store, items: list[dict], auto: dict, pace: Optional[float], saved: float, today: date) -> Optional[dict]:
    """Trim the biggest discretionary category by 20%: what it saves a month and how much sooner it lands."""
    pending = [w for w in items if w["status"] != "ready"]
    if not pending or not auto["months"]:
        return None
    avg = _categories(store, [m["month"] for m in auto["months"]])
    options = [(k, avg.get(k, 0.0)) for k in DISCRETIONARY if k in store.categories.by_key]
    key, monthly = max(options, key=lambda kv: kv[1], default=(None, 0.0))
    if not key or monthly < 50:
        return None
    cut = round(monthly * TIP_SHARE, 2)
    new_pace = (pace or 0) + cut
    # The wish it changes most: one that misses its target, else the last one on the list.
    late = [w for w in pending if w["target_check"] and not w["target_check"]["on_track"]]
    wish = late[0] if late else pending[-1]
    tip = {"category": key, "monthly": monthly, "share": TIP_SHARE, "cut": cut, "pace": pace,
           "new_pace": round(new_pace, 2), "wish_id": wish["id"], "wish": wish["name"],
           "kind": None, "days_sooner": None, "ready_date": None, "fixes_target": None}
    if new_pace <= 0:
        tip["kind"] = "not_enough"
        return tip
    _, new_ready = _when(wish["needed"], new_pace, today)
    tip["ready_date"] = new_ready
    if wish["status"] == "never":
        tip["kind"] = "reachable"
    else:
        tip["kind"] = "sooner"
        tip["days_sooner"] = round(wish["needed"] / pace * DAYS_PER_MONTH - wish["needed"] / new_pace * DAYS_PER_MONTH)
    if wish["target"]:
        tip["fixes_target"] = new_ready <= wish["target"]
    return tip
