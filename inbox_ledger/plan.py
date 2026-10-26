"""Plan: the days ahead of the month in progress.

Everything here is derived from the ledger on the fly, except what you change, which is kept in
four small tables of its own (created on the store's SQLite connection, never touching its schema):

* expected charges, detected automatically: regular bills and subscriptions that have not come yet
  this month, plus the next pay-later instalments;
* one-offs you plan yourself ("Birthday dinner, AED 400, Nov 12");
* an allowance per category for the rest of the month, and a savings goal.

The projection is plain arithmetic, in whole currency units so the sum you see always adds up:

    money in − spent so far − expected charges − planned one-offs − allowances − savings goal = buffer
"""
from __future__ import annotations

import calendar
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from . import paylater
from .merchants import merchant_key
from .store import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, amount REAL, date TEXT, category TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS plan_overrides (
  key TEXT PRIMARY KEY, month TEXT, amount REAL, date TEXT, state TEXT
);
CREATE TABLE IF NOT EXISTS plan_allowances (
  month TEXT, category TEXT, amount REAL, PRIMARY KEY (month, category)
);
CREATE TABLE IF NOT EXISTS plan_goals (
  month TEXT PRIMARY KEY, amount REAL
);
"""

LOOKBACK = 4          # recurring: look at the last 4 complete months...
MIN_SEEN = 3          # ...and require the charge in at least 3 of them
AMOUNT_TOLERANCE = 0.15
DAY_TOLERANCE = 4     # "similar day of the month": within 4 days of the usual day
MAX_PER_MONTH = 2     # a merchant you pay more often than this is shopping, not a bill
GRACE_DAYS = 7        # a bill this many days late is still expected; later than that it was probably skipped
AHEAD_DAYS = 14       # the timeline also looks this far into next month
TYPICAL_MONTHS = 3    # allowances start from the average of the last 3 complete months


# ---- small date helpers ----------------------------------------------------------

def _ym(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def _month_bounds(month: str) -> tuple[date, date]:
    y, m = map(int, month.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _shift(month: str, n: int) -> str:
    y, m = map(int, month.split("-"))
    i = y * 12 + m - 1 + n
    return f"{i // 12}-{i % 12 + 1:02d}"


def _on_day(month: str, day: int) -> date:
    start, end = _month_bounds(month)
    return start.replace(day=min(max(day, 1), end.day))


def _add_month(d: date) -> date:
    nxt = _shift(_ym(d), 1)
    return _on_day(nxt, d.day)


def _parse_date(s: str) -> Optional[date]:
    for fmt in ("%Y-%m-%d", "%d %b, %Y", "%d %B, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def _whole(v: float) -> int:
    """Round half away from zero, as people do (not banker's rounding)."""
    return int(v + 0.5) if v >= 0 else -int(-v + 0.5)


# ---- persistence ---------------------------------------------------------------

def ensure(st: Store) -> None:
    if not getattr(st, "_plan_ready", False):
        with st.db:
            st.db.executescript(SCHEMA)
        st._plan_ready = True


def add_item(st: Store, name: str, amount: float, day: str, category: str) -> dict:
    ensure(st)
    with st.db:
        cur = st.db.execute("INSERT INTO plan_items (name, amount, date, category, created_at) VALUES (?,?,?,?,?)",
                            (name, round(amount, 2), day, category, datetime.now().isoformat(timespec="seconds")))
    return get_item(st, cur.lastrowid)


def get_item(st: Store, item_id: int) -> Optional[dict]:
    ensure(st)
    r = st.db.execute("SELECT * FROM plan_items WHERE id=?", (item_id,)).fetchone()
    return dict(r) if r else None


def update_item(st: Store, item_id: int, **changes) -> Optional[dict]:
    ensure(st)
    fields = {k: v for k, v in changes.items() if k in ("name", "amount", "date", "category") and v is not None}
    if fields:
        with st.db:
            st.db.execute(f"UPDATE plan_items SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                          (*fields.values(), item_id))
    return get_item(st, item_id)


def delete_item(st: Store, item_id: int) -> bool:
    ensure(st)
    with st.db:
        return st.db.execute("DELETE FROM plan_items WHERE id=?", (item_id,)).rowcount > 0


def set_override(st: Store, key: str, month: str, amount: Optional[float] = None, day: Optional[str] = None,
                 state: Optional[str] = None) -> None:
    """Change a detected item: its amount, its date, or whether it happens ("skip" / "include").
    All three None forgets every change to it."""
    ensure(st)
    with st.db:
        if amount is None and day is None and state is None:
            st.db.execute("DELETE FROM plan_overrides WHERE key=?", (key,))
        else:
            st.db.execute("INSERT OR REPLACE INTO plan_overrides VALUES (?,?,?,?,?)",
                          (key, month, None if amount is None else round(amount, 2), day, state))


def set_allowance(st: Store, month: str, category: str, amount: Optional[float]) -> None:
    ensure(st)
    with st.db:
        if amount is None:
            st.db.execute("DELETE FROM plan_allowances WHERE month=? AND category=?", (month, category))
        else:
            st.db.execute("INSERT OR REPLACE INTO plan_allowances VALUES (?,?,?)", (month, category, _whole(amount)))


def set_goal(st: Store, month: str, amount: Optional[float]) -> None:
    ensure(st)
    with st.db:
        if amount is None:
            st.db.execute("DELETE FROM plan_goals WHERE month=?", (month,))
        else:
            st.db.execute("INSERT OR REPLACE INTO plan_goals VALUES (?,?)", (month, _whole(amount)))


def reset(st: Store, month: str) -> None:
    """Forget changes to detected items, allowances and the goal for one month (planned one-offs stay)."""
    ensure(st)
    with st.db:
        st.db.execute("DELETE FROM plan_overrides WHERE month=?", (month,))
        st.db.execute("DELETE FROM plan_allowances WHERE month=?", (month,))
        st.db.execute("DELETE FROM plan_goals WHERE month=?", (month,))


# ---- recurring detection ---------------------------------------------------------

def recurring(st: Store, month: str) -> list[dict]:
    """Merchants charged (or paying you) about monthly: seen in ≥3 of the 4 months before `month`,
    on a similar day (±4) and for a similar amount (±15%). Pay-later charges are left to `instalments`."""
    history = [_shift(month, -i) for i in range(LOOKBACK, 0, -1)]
    groups: dict[tuple, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for m in history:
        for t in st.transactions(month=m, internal="hide", limit=100000):
            if t["direction"] not in ("out", "in") or t["extra"].get("via"):
                continue
            groups[(t["direction"], t["merchant_key"])][m].append(t)
    found = []
    for (direction, key), by_month in groups.items():
        if len(by_month) < MIN_SEEN or any(len(v) > MAX_PER_MONTH for v in by_month.values()):
            continue
        middle = statistics.median(t["amount_base"] for v in by_month.values() for t in v)
        picks = [min(v, key=lambda t: abs(t["amount_base"] - middle)) for v in by_month.values()]
        amount = statistics.median(t["amount_base"] for t in picks)
        day = statistics.median(int(t["occurred_at"][8:10]) for t in picks)
        steady = [t for t in picks if amount and abs(t["amount_base"] - amount) <= AMOUNT_TOLERANCE * amount
                  and abs(int(t["occurred_at"][8:10]) - day) <= DAY_TOLERANCE]
        if len(steady) < MIN_SEEN:
            continue
        last = max(steady, key=lambda t: t["occurred_at"])
        found.append({
            "direction": direction, "merchant_key": key, "merchant": last["merchant"], "kind": last["kind"],
            "category": last["category"], "day": _whole(statistics.median(int(t["occurred_at"][8:10]) for t in steady)),
            "amount": round(statistics.median(t["amount_base"] for t in steady), 2),
            "currency": last["currency"], "amount_original": last["amount"],
            "seen": len(steady), "of": LOOKBACK,
        })
    return sorted(found, key=lambda r: (r["day"], r["merchant"]))


# ---- pay-later instalments -------------------------------------------------------------

def instalments(st: Store, until: date, as_of: Optional[date] = None) -> list[dict]:
    """Next instalments of open pay-later orders, due up to `until` (from the provider's own emails)."""
    out = []
    as_of = as_of or date.today()
    now = datetime(as_of.year, as_of.month, as_of.day, tzinfo=timezone.utc) + timedelta(days=1)
    for p in st.providers:
        events = [paylater.Event(r["message_id"], r["provider"], r["kind"], datetime.fromisoformat(r["at"]),
                                 r["store"] or "", r["order_id"] or "", r["paid"] or 0.0, r["remaining"], r["total"],
                                 r["refunded"], r["instalments"], r["next_due"] or "", bool(r["full_refund"]))
                  for r in st.db.execute("SELECT * FROM paylater_events WHERE provider=?", (p.name,))]
        if not events:
            continue
        cat = _store_category(st, p.name)
        for o in paylater.open_orders(events, now):
            payments = sorted((e for e in events if e.kind in paylater.PAYMENT_KINDS and e.order
                               and paylater.same_order(e.order, o["order"])), key=lambda e: e.at)
            per = round(o["total"] / o["instalments"], 2) if o["total"] and o["instalments"] else \
                (payments[-1].paid if payments else o["remaining"])
            if not per:
                continue
            due, estimated = _parse_date(o["next_due"]), False
            if not due:
                last = o["last_paid"] or o["purchased"]
                if not last:
                    continue
                due, estimated = _add_month(last.date()), True
            left, n = round(o["remaining"], 2), o["instalments"]
            while left > 0.005 and due <= until:
                amount = round(min(per, left), 2)
                number = n - _whole(left / per) + 1 if n else None
                out.append({"provider": p.name, "order": o["order"], "store": o["store"] or p.name, "date": due,
                            "amount": amount, "number": number, "of": n, "estimated": estimated,
                            "remaining": left, "category": cat.get(merchant_key(o["store"] or p.name, location=False),
                                                                   cat.get("", "shopping"))})
                left = round(left - amount, 2)
                due, estimated = _add_month(due), True
    return out


def _store_category(st: Store, provider: str) -> dict[str, str]:
    """The category each store's pay-later charges were filed under (latest wins)."""
    out: dict[str, str] = {}
    for t in sorted(st.transactions(via=provider, limit=100000), key=lambda t: t["occurred_at"]):
        out[t["merchant_key"]] = t["category"]
    fallback = "shopping" if "shopping" in st.categories.by_key else "other"
    out.setdefault("", fallback)
    return out


# ---- the plan --------------------------------------------------------------------

def plan(st: Store, month: str, today: Optional[date] = None) -> dict:
    ensure(st)
    today = today or date.today()
    start, end = _month_bounds(month)
    currency = st.categories.base_currency
    base = {"month": month, "today": today.isoformat(), "currency": currency,
            "start": start.isoformat(), "end": end.isoformat(), "days_in_month": end.day}
    if today > end:
        return {**base, "status": "past"}
    as_of = max(today, start)
    days_left = (end - as_of).days + 1
    horizon = end + timedelta(days=AHEAD_DAYS)
    s = st.summary(month)
    overrides = {r["key"]: dict(r) for r in st.db.execute("SELECT * FROM plan_overrides")}

    items: list[dict] = []
    paid: list[dict] = []
    this_month = st.transactions(month=month, internal="hide", limit=100000)
    seen = defaultdict(list)
    for t in this_month:
        seen[(t["direction"], t["merchant_key"])].append(t)

    # 1. Regular charges (and regular income) that haven't come yet.
    for r in recurring(st, month):
        so_far = [t for t in seen.get((r["direction"], r["merchant_key"]), []) if t["occurred_at"][:10] <= as_of.isoformat()]
        occurrences = []
        if so_far:
            t = max(so_far, key=lambda t: t["occurred_at"])
            paid.append({"name": r["merchant"], "merchant_key": r["merchant_key"], "kind": r["kind"],
                         "category": r["category"], "direction": r["direction"], "date": t["occurred_at"][:10],
                         "amount": round(t["amount_base"], 2)})
        else:
            occurrences.append(_on_day(month, r["day"]))
        nxt = _on_day(_shift(month, 1), r["day"])
        if nxt <= horizon:
            occurrences.append(nxt)
        for when in occurrences:
            usual = f"Usually on the {_ordinal(r['day'])}"
            fx = f" · {r['currency']} {r['amount_original']:,.2f}" if r["currency"] != currency else ""
            items.append(_detected(
                key=f"rec:{r['direction']}:{r['merchant_key']}:{_ym(when)}", kind="income" if r["direction"] == "in" else "recurring",
                name=r["merchant"], merchant_key=r["merchant_key"], merchant_kind=r["kind"], category=r["category"],
                amount=r["amount"], when=when, as_of=as_of,
                note=f"{usual} · {r['seen']} of the last {r['of']} months{fx}", overrides=overrides))

    # 2. Pay-later instalments.
    for i in instalments(st, horizon, as_of):
        num = f"instalment {i['number']} of {i['of']}" if i["number"] and i["of"] else "next instalment"
        items.append(_detected(
            key=f"bnpl:{i['provider']}:{i['order']}:{i['date'].isoformat()}", kind="paylater", name=i["store"],
            merchant_key=merchant_key(i["store"], location=False), merchant_kind="card", category=i["category"],
            amount=i["amount"], when=i["date"], as_of=as_of,
            note=f"{i['provider']} · {num}{' · date estimated' if i['estimated'] else ''}", overrides=overrides,
            provider=i["provider"]))

    # 3. Your own one-offs.
    for r in st.db.execute("SELECT * FROM plan_items WHERE date>=? AND date<=? ORDER BY date, id",
                           (start.isoformat(), horizon.isoformat())):
        when = date.fromisoformat(r["date"])
        items.append({"key": f"item:{r['id']}", "id": r["id"], "kind": "planned", "name": r["name"],
                      "merchant_key": "", "merchant_kind": "", "category": r["category"], "direction": "out",
                      "amount": round(r["amount"], 2), "suggested": None, "date": r["date"], "usual": r["date"],
                      "state": "auto", "edited": False, "included": True, "passed": when < as_of,
                      "counts": as_of <= when <= end, "note": "Planned by you"})
    items.sort(key=lambda x: (x["date"], x["kind"] != "income", x["name"].lower()))

    counted = [x for x in items if x["counts"]]
    exp_out = [x for x in counted if x["direction"] == "out" and x["kind"] != "planned"]
    exp_in = [x for x in counted if x["direction"] == "in"]
    planned = [x for x in counted if x["kind"] == "planned"]

    # 4. Allowances: typical spend minus what's spent and what's already expected, per category.
    tr = st.trends(_shift(month, -1), TYPICAL_MONTHS)
    n_typ = len(tr["months"])
    spent_by = {c["category"]: c["total"] for c in s["by_category"]}
    expected_by: dict[str, float] = defaultdict(float)
    for x in exp_out:
        expected_by[x["category"]] += _whole(x["amount"])
    saved = {r["category"]: r["amount"] for r in st.db.execute("SELECT * FROM plan_allowances WHERE month=?", (month,))}
    allowances = []
    for c in st.categories.items:
        k = c["key"]
        if k == "income":
            continue
        typical = _whole(sum(tr["categories"].get(k, [])) / n_typ) if n_typ else 0
        if typical <= 0 and k not in saved:
            continue
        spent_k, expected_k = _whole(spent_by.get(k, 0)), _whole(expected_by.get(k, 0))
        suggested = max(0, typical - spent_k - expected_k)
        amount = _whole(saved[k]) if k in saved else suggested
        allowances.append({"category": k, "typical": typical, "spent": spent_k, "expected": expected_k,
                           "suggested": suggested, "amount": amount, "edited": k in saved,
                           "per_day": round(amount / days_left, 2)})
    allowances.sort(key=lambda a: (-a["typical"], a["category"]))

    # 5. Savings goal: by default, what you already moved to your own accounts this month.
    goal_row = st.db.execute("SELECT amount FROM plan_goals WHERE month=?", (month,)).fetchone()
    moved = _whole(s.get("moved") or 0)
    goal = {"amount": _whole(goal_row["amount"]) if goal_row else moved, "suggested": moved, "moved": moved,
            "edited": goal_row is not None}

    totals = {
        "money_in": _whole(s["received"]),
        "expected_in": sum(_whole(x["amount"]) for x in exp_in),
        "spent": _whole(s["spent"]),
        "expected": sum(_whole(x["amount"]) for x in exp_out),
        "planned": sum(_whole(x["amount"]) for x in planned),
        "allowances": sum(a["amount"] for a in allowances),
        "goal": goal["amount"],
    }
    totals["buffer"] = (totals["money_in"] + totals["expected_in"] - totals["spent"] - totals["expected"]
                        - totals["planned"] - totals["allowances"] - totals["goal"])

    return {**base, "status": "current" if start <= today else "future", "as_of": as_of.isoformat(),
            "days_left": days_left, "horizon": horizon.isoformat(), "items": items, "paid": paid,
            "allowances": allowances, "goal": goal, "totals": totals, "typical_months": tr["months"],
            "daily": _daily(st.transactions(month=month, internal="show", limit=100000), start, end, as_of,
                            totals, goal, items, days_left)}


def _detected(*, key: str, kind: str, name: str, merchant_key: str, merchant_kind: str, category: str, amount: float,
              when: date, as_of: date, note: str, overrides: dict, provider: str = "") -> dict:
    o = overrides.get(key) or {}
    late = (as_of - when).days
    state = o.get("state") or "auto"
    # A charge a few days late is still coming (today); much later, it probably isn't, unless you say so.
    if late > GRACE_DAYS:
        included = state == "include"
        status = "missed"
    else:
        included = state != "skip"
        status = "late" if late > 0 else "due"
    day = date.fromisoformat(o["date"]) if o.get("date") else (as_of if late > 0 else when)
    _, end = _month_bounds(_ym(as_of))
    return {"key": key, "id": None, "kind": kind, "name": name, "merchant_key": merchant_key,
            "merchant_kind": merchant_kind, "category": category, "direction": "in" if kind == "income" else "out",
            "amount": o["amount"] if o.get("amount") is not None else amount, "suggested": amount,
            "date": day.isoformat(), "usual": when.isoformat(), "state": state, "status": status,
            "edited": bool(o), "included": included, "passed": False, "provider": provider,
            "counts": included and as_of <= day <= end, "note": note}


def _daily(txs: list[dict], start: date, end: date, as_of: date, totals: dict, goal: dict, items: list[dict],
           days_left: int) -> list[dict]:
    """Money left after savings at the end of each day: what actually happened before today, then the plan.

    The projection starts from money in − spent − the whole savings goal, then each day takes its share of
    the allowances and that day's expected and planned items, so the last day lands exactly on the buffer."""
    flow: dict[str, float] = defaultdict(float)
    for t in txs:  # every visible transaction, moves to your own accounts included
        flow[t["occurred_at"][:10]] += t["amount_base"] if t["direction"] == "in" else -t["amount_base"]
    by_day: dict[str, list] = defaultdict(list)
    for x in items:
        if x["counts"]:
            by_day[x["date"]].append(x)
    per_day = totals["allowances"] / days_left if days_left else 0.0
    level = totals["money_in"] - totals["spent"] - totals["goal"]
    out, running, d = [], 0.0, start
    while d <= end:
        key = d.isoformat()
        if d < as_of:
            running += flow.get(key, 0.0)
            out.append({"day": key, "actual": round(running, 2)})
        else:
            today = by_day.get(key, [])
            level += sum(_whole(x["amount"]) * (1 if x["direction"] == "in" else -1) for x in today) - per_day
            out.append({"day": key, "projected": round(level, 2), "allowance": round(per_day, 2),
                        "items": [{"name": x["name"], "amount": _whole(x["amount"]), "direction": x["direction"]}
                                  for x in today]})
        d += timedelta(days=1)
    if out and "projected" in out[-1]:
        out[-1]["projected"] = float(totals["buffer"])  # no rounding drift on the day that matters
    return out


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
