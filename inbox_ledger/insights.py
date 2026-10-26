"""What the month means in plain words, and the fixed / everyday split the dashboard draws from.

Everything here is computed from the store's own queries, so it reads the same whether or not
the summary endpoint already carries the newer fields. Fixed = rent, bills and subscriptions
(or whichever categories are flagged `fixed`); everyday = everything else.

Line texts use `{0}`, `{1}` for amounts (listed in `amounts`, so the dashboard formats them in
the reader's currency style) and `{category}` for the category name.
"""
from __future__ import annotations

import calendar
from datetime import date
from typing import Optional

from .store import Store, _prev_month

DEFAULT_FIXED = ("housing", "bills", "subscriptions")
MAX_LINES = 4
CHANGE_THRESHOLD = 0.15     # a category has to move 15% against its 3-month average
CHANGE_MIN_AMOUNT = 100.0   # and involve at least this much
BUDGET_NEAR = 0.85          # "nearly used up"
STREAK_MIN_VISITS = 4
MISSING_BILL_GRACE = 2      # days after its usual date before a bill counts as not arrived


def fixed_keys(store: Store) -> list[str]:
    """Categories whose spend is fixed: flagged `fixed: true`, else the built-in three."""
    return [c["key"] for c in store.categories.items if c.get("fixed", c["key"] in DEFAULT_FIXED)]


def _days_in(month: str) -> int:
    y, m = map(int, month.split("-"))
    return calendar.monthrange(y, m)[1]


def _month_label(month: str) -> str:
    y, m = map(int, month.split("-"))
    return calendar.month_name[m]


def _pct(now: float, base: float) -> int:
    return int(round((now - base) / base * 100)) if base else 0


def _line(text: str, amounts: list[float], to: str, **extra) -> dict:
    return {"text": text, "amounts": [round(a, 2) for a in amounts], "to": to, **extra}


def build(store: Store, month: str, *, demo: bool = False, today: Optional[date] = None,
          months: int = 12) -> dict:
    today = today or date.today()
    fixed = fixed_keys(store)
    marks = ",".join("?" * len(fixed)) or "''"
    not_fixed = f"category NOT IN ({marks})"
    c = "counted=1"
    db = store.db

    s = store.summary(month)
    days = _days_in(month)
    in_progress = not demo and month == today.isoformat()[:7]
    elapsed = min(today.day, days) if in_progress else days
    fixed_total = round(sum(x["total"] for x in s["by_category"] if x["category"] in fixed), 2)
    everyday_total = round(s["spent"] - fixed_total, 2)
    prev = _prev_month(month)

    previous_to_date = None
    if in_progress:
        previous_to_date = round(db.execute(
            f"SELECT coalesce(sum(spend),0) FROM transactions WHERE month=? AND {c}"
            f" AND CAST(substr(occurred_at,9,2) AS INT) <= ?", (prev, elapsed)).fetchone()[0], 2)

    by_day = [dict(r) for r in db.execute(
        f"SELECT substr(occurred_at,1,10) AS day, round(sum(spend),2) AS total,"
        f" round(coalesce(sum(CASE WHEN {not_fixed} THEN spend END),0),2) AS everyday"
        f" FROM transactions WHERE month=? AND spend!=0 AND {c} GROUP BY day HAVING round(sum(spend),2)!=0 ORDER BY day",
        (*fixed, month))]
    by_hour = [dict(r) for r in db.execute(
        f"SELECT CAST(substr(occurred_at,12,2) AS INT) AS hour, round(sum(spend),2) AS total,"
        f" round(coalesce(sum(CASE WHEN {not_fixed} THEN spend END),0),2) AS everyday"
        f" FROM transactions WHERE month=? AND spend>0 AND {c} GROUP BY hour", (*fixed, month))]

    visited = db.execute(
        f"SELECT merchant, merchant_key, category, sum(spend>0) AS count, round(sum(spend),2) AS total"
        f" FROM transactions WHERE month=? AND spend>0 AND {c} GROUP BY merchant_key"
        f" ORDER BY count DESC, total DESC LIMIT 1", (month,)).fetchone()
    most_visited = ({"merchant": visited["merchant"], "merchant_key": visited["merchant_key"],
                     "category": visited["category"], "count": visited["count"], "total": visited["total"]}
                    if visited else None)
    big = db.execute(
        f"SELECT merchant, category, amount_base, occurred_at FROM transactions WHERE month=? AND spend>0"
        f" AND {c} AND {not_fixed} ORDER BY spend DESC LIMIT 1", (month, *fixed)).fetchone()
    biggest_everyday = ({"merchant": big["merchant"], "amount": big["amount_base"], "date": big["occurred_at"],
                         "category": big["category"]} if big else None)

    out = {
        "month": month, "in_progress": in_progress, "elapsed_days": elapsed, "days": days,
        "fixed": fixed_total, "everyday": everyday_total, "fixed_keys": fixed,
        "previous_spent_to_date": previous_to_date,
        "by_day": by_day, "by_hour": by_hour,
        "most_visited": most_visited, "biggest_everyday": biggest_everyday,
        "lines": _lines(store, s, month, fixed, in_progress, elapsed),
        "review": [] if demo or in_progress else _review(store, s, month, fixed),
        **_window(store, month, fixed, months),
    }
    return out


# ---- the lines ---------------------------------------------------------------

def _lines(store: Store, s: dict, month: str, fixed: list[str], in_progress: bool, elapsed: int) -> list[dict]:
    db, c = store.db, "counted=1"
    have = [m["month"] for m in store.months() if m["month"] < month][-3:]
    prev = _prev_month(month)
    lines: list[dict] = []

    # 1. A category well above or below its 3-month average (to the same day while the month runs).
    if len(have) == 3:
        marks = ",".join("?" * len(have))
        to_date = " AND CAST(substr(occurred_at,9,2) AS INT) <= ?" if in_progress else ""
        hist: dict[str, float] = {}
        for r in db.execute(f"SELECT category, sum(spend) FROM transactions WHERE month IN ({marks}) AND spend!=0"
                            f" AND {c}{to_date} GROUP BY category", (*have, *([elapsed] if in_progress else []))):
            hist[r[0]] = r[1] / 3
        movers = []
        for cat in s["by_category"]:
            key, now = cat["category"], cat["total"]
            avg = hist.get(key, 0.0)
            if key in fixed or key == "other" or avg <= 0 or max(now, avg) < CHANGE_MIN_AMOUNT:
                continue
            delta = (now - avg) / avg
            if abs(delta) >= CHANGE_THRESHOLD:
                movers.append((abs(now - avg), key, now, avg, delta))
        for _, key, now, avg, delta in sorted(movers, reverse=True)[:2]:
            when = "usual by this point in the month" if in_progress else "3-month average"
            lines.append(_line(f"{{category}} is {abs(int(round(delta * 100)))}% {'above' if delta > 0 else 'below'}"
                               f" your {when} ({{0}} vs {{1}})", [now, avg], "category", category=key, kind="change"))

    # 2. Budgets: over the limit first, then the one closest to it.
    spent = {x["category"]: x["total"] for x in s["by_category"]}
    over, near = [], []
    for key, limit in (s.get("budgets") or {}).items():
        used = spent.get(key, 0)
        if not limit or used <= 0:
            continue
        if used > limit:
            over.append((used - limit, key, used, limit))
        elif key not in fixed and used / limit >= BUDGET_NEAR:
            near.append((used / limit, key, used, limit))
    for diff, key, used, limit in sorted(over, reverse=True)[:2]:
        lines.append(_line("{category} is {0} over its {1} limit", [diff, limit], "category", category=key, kind="budget"))
    covered = {l["category"] for l in lines}  # a category already explained above needs no second line
    near = [x for x in near if x[1] not in covered]
    if not over and near:
        share, key, used, limit = max(near)
        lines.append(_line(f"{{category}} has used {int(round(share * 100))}% of its {{0}} limit", [limit],
                           "category", category=key, kind="budget"))

    # 3. A fixed bill that came every month lately but not yet this one (only while the month runs).
    if in_progress and len(have) == 3 and fixed:
        marks, fmarks = ",".join("?" * len(have)), ",".join("?" * len(fixed))
        seen: dict[str, dict] = {}
        for r in db.execute(
                f"SELECT merchant_key, merchant, category, month, min(CAST(substr(occurred_at,9,2) AS INT)) AS day,"
                f" round(sum(spend),2) AS total FROM transactions WHERE month IN ({marks}) AND category IN ({fmarks})"
                f" AND spend>0 AND {c} GROUP BY merchant_key, month ORDER BY month", (*have, *fixed)):
            d = seen.setdefault(r["merchant_key"], {"merchant": r["merchant"], "category": r["category"],
                                                     "months": 0, "day": 0, "total": 0.0})
            d["months"] += 1
            d["day"] = max(d["day"], r["day"])
            d["total"] = r["total"]  # the latest month's amount
        this = {r[0] for r in db.execute(f"SELECT DISTINCT merchant_key FROM transactions WHERE month=? AND spend>0 AND {c}",
                                         (month,))}
        due = [(d["day"], k, d) for k, d in seen.items()
               if d["months"] == 3 and k not in this and d["day"] + MISSING_BILL_GRACE <= elapsed]
        for _, key, d in sorted(due)[:1]:
            lines.append(_line(f"{d['merchant']}’s usual {{0}} bill hasn’t arrived yet this month", [d["total"]],
                               "activity", category=d["category"], q=d["merchant"], kind="missing"))

    # 4. The place you went to most: a record, or more often than last month.
    fmarks = ",".join("?" * len(fixed)) or "''"
    top = db.execute(
        f"SELECT merchant, merchant_key, category, sum(spend>0) AS count, round(sum(spend),2) AS total"
        f" FROM transactions WHERE month=? AND spend>0 AND {c} AND category NOT IN ({fmarks})"
        f" GROUP BY merchant_key ORDER BY count DESC, total DESC LIMIT 1", (month, *fixed)).fetchone()
    if top and top["count"] >= STREAK_MIN_VISITS:
        history = {r[0]: r[1] for r in db.execute(
            f"SELECT month, sum(spend>0) FROM transactions WHERE merchant_key=? AND month<? AND spend>0 AND {c}"
            f" GROUP BY month", (top["merchant_key"], month))}
        best = max(history.values(), default=0)
        last = history.get(prev, 0)
        if top["count"] > best and history:
            lines.append(_line(f"{top['count']} {top['merchant']} visits, your most in a month ({{0}})", [top["total"]],
                               "activity", category=top["category"], q=top["merchant"], kind="merchant"))
        elif top["count"] > last:
            lines.append(_line(f"{top['count']} {top['merchant']} visits this month, up from {last} in {_month_label(prev)}"
                               f" ({{0}})", [top["total"]], "activity", category=top["category"], q=top["merchant"],
                               kind="merchant"))

    # 5. Pay later: one line, never a box. It always keeps its place, since the box it replaces is gone.
    paylater = None
    for p in s.get("pay_later") or []:
        if p.get("owed", 0) > 0 or p.get("paid", 0) > 0:
            n = len(p.get("open_orders") or [])
            text = (f"{p['provider']}: {{0}} paid this month, {{1}} still to pay on {n} order{'' if n == 1 else 's'}"
                    if p.get("owed", 0) > 0 else f"{p['provider']}: {{0}} paid this month, nothing left to pay")
            paylater = _line(text, [p.get("paid", 0), p.get("owed", 0)], "activity", via=p["provider"], kind="paylater")
            break

    # When there is more to say than fits, a second category line gives way to a different kind of line.
    room = MAX_LINES - (1 if paylater else 0)
    if len(lines) > room:
        changes = [i for i, l in enumerate(lines) if l["kind"] == "change"]
        if len(changes) > 1:
            del lines[changes[-1]]
    return lines[:room] + ([paylater] if paylater else [])


# ---- a closed month in review --------------------------------------------------

def _review(store: Store, s: dict, month: str, fixed: list[str]) -> list[dict]:
    months = [m for m in store.months() if m["month"] <= month]
    if not months or s["spent"] <= 0:
        return []
    prev = _prev_month(month)
    prev_name = _month_label(prev)
    out: list[dict] = []
    spent, last = s["spent"], s.get("previous_spent") or 0
    window = months[-6:]
    text, amounts = "Spent {0}", [spent]
    if last > 0:
        p = _pct(spent, last)
        text += ", the same as " if p == 0 else f", {abs(p)}% {'more' if p > 0 else 'less'} than "
        text += prev_name
    if len(window) >= 3:
        avg = sum(m["spent"] for m in window) / len(window)
        p = _pct(spent, avg)
        text += " and in line with" if abs(p) < 1 else f" and {abs(p)}% {'above' if p > 0 else 'below'}"
        text += f" your {len(window)}-month average"
    out.append(_line(text, amounts, "activity", kind="total"))

    if last > 0:
        before = {r[0]: r[1] for r in store.db.execute(
            "SELECT category, sum(spend) FROM transactions WHERE month=? AND spend!=0 AND counted=1 GROUP BY category", (prev,))}
        moves = [(abs(x["total"] - before.get(x["category"], 0)), x["category"], x["total"] - before.get(x["category"], 0))
                 for x in s["by_category"] if x["category"] not in fixed]
        if moves:
            _, key, diff = max(moves)
            if abs(diff) >= 1:
                out.append(_line(f"Biggest move: {{category}}, {{0}} {'more' if diff > 0 else 'less'} than {prev_name}",
                                 [abs(diff)], "category", category=key, kind="move"))

    received, moved = s.get("received") or 0, s.get("moved") or 0
    if received > 0:
        left = received - spent - moved
        share = int(round(moved / received * 100))
        text = (f"Put aside {share}% of what came in" if moved > 0 else "Nothing was moved to savings") + (
            "; {0} was left unspent" if left >= 0 else "; spent {0} more than came in")
        out.append(_line(text, [abs(left)], "activity", kind="savings"))
    return out[:3]


# ---- the trends window -----------------------------------------------------------

def _window(store: Store, month: str, fixed: list[str], months: int) -> dict:
    """Everyday spend per month and per weekday over the same window /api/trends uses."""
    have = [m["month"] for m in store.months() if m["month"] <= month][-max(1, min(months, 36)):]
    out = {"months": have, "everyday_months": [], "weekday_everyday": [0.0] * 7}
    if not have:
        return out
    db, c = store.db, "counted=1"
    marks = ",".join("?" * len(have))
    fmarks = ",".join("?" * len(fixed)) or "''"
    per = {r[0]: r[1] for r in db.execute(
        f"SELECT month, sum(spend) FROM transactions WHERE month IN ({marks}) AND category NOT IN ({fmarks})"
        f" AND spend!=0 AND {c} GROUP BY month", (*have, *fixed))}
    out["everyday_months"] = [round(per.get(m, 0.0), 2) for m in have]
    first = f"{have[0]}-01"
    last = db.execute(f"SELECT max(substr(occurred_at,1,10)) FROM transactions WHERE month=? AND {c}", (have[-1],)).fetchone()[0]
    if not last:
        return out
    n = dict(db.execute(
        "WITH RECURSIVE d(x) AS (SELECT date(?) UNION ALL SELECT date(x, '+1 day') FROM d WHERE x < date(?))"
        " SELECT (CAST(strftime('%w', x) AS INT) + 6) % 7, count(*) FROM d GROUP BY 1", (first, last)).fetchall())
    for w, total in db.execute(
            f"SELECT (CAST(strftime('%w', substr(occurred_at,1,10)) AS INT) + 6) % 7, sum(spend) FROM transactions"
            f" WHERE month IN ({marks}) AND category NOT IN ({fmarks}) AND spend!=0 AND {c} GROUP BY 1", (*have, *fixed)):
        out["weekday_everyday"][w] = round(total / max(n.get(w, 1), 1), 2)
    return out
