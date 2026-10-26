"""Make totals reconcile: refunds and paybacks cancel what they undo.

Works on the row dicts `Store.rebuild()` builds, after categories and the user's
corrections are applied. Every counted row ends up with two numbers in the base
currency: `spend` (what it adds to spending, negative for a refund) and `income`
(what it adds to money received). Summaries only ever add those up.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from itertools import combinations

from .paylater import same_order

REFUND_DAYS = 120  # a refund undoes a purchase made at most this long before
SETTLE_DAYS = 45   # money sent to a person and returned within this window cancels out
_MAX_OPEN = 10     # transfers to one person considered together when looking for a zero-sum


def is_refund(r: dict) -> bool:
    """A card credit: a refund or a reversal, not income."""
    return r["direction"] == "in" and r["kind"] == "card_purchase"


def _at(r: dict) -> datetime:
    return datetime.fromisoformat(r["occurred_at"])


def _cents(r: dict) -> int:
    return round(r["amount_base"] * 100)


def apply(rows: list[dict]) -> None:
    """Match refunds and settle transfers, then set spend / income / counted on every row."""
    live = [r for r in rows if not r["hidden"] and not r["mirror_of"]]
    match_refunds(live)
    settle_transfers(live)
    mark_moves_back(live)
    for r in rows:
        r["spend"], r["income"], r["counted"] = _contribution(r)


def _contribution(r: dict) -> tuple[float, float, int]:
    if r["hidden"] or r["mirror_of"] or r["extra"].get("settled"):
        return 0.0, 0.0, 0
    amount, direction = r["amount_base"], r["direction"]
    if direction == "out":
        return amount, 0.0, 1
    if direction == "in":
        if is_refund(r):
            return -amount, 0.0, 1
        back = r.get("payback", 0.0)  # the part of a credit that only returns money you sent
        return -back, round(amount - back, 2), 1
    return 0.0, 0.0, 1  # between your own accounts


# ---- moves between your own accounts ---------------------------------------------

def main_account(rows: list[dict]) -> str:
    """The account your income lands in (the one credited the most), or "" when none is known."""
    totals: dict[str, float] = {}
    for r in rows:
        if r["direction"] == "in" and r["kind"] == "account_credit" and r["account"] and not is_refund(r):
            totals[r["account"]] = totals.get(r["account"], 0.0) + r["amount_base"]
    return max(totals, key=totals.get) if totals else ""


def mark_moves_back(rows: list[dict]) -> None:
    """Saved is net: a move between your own accounts that leaves any account other than the main one, or
    lands in the main one, is money coming back and is marked `moved_back` so the totals take it off.

    This needs the alert to name the account; when it does not, or no income has arrived yet, every
    own-account move counts as saved (docs/definitions.md, "Which way a move went")."""
    main = main_account(rows)
    for r in rows:
        r["extra"].pop("moved_back", None)
        if r["direction"] != "internal" or not main or not r["account"]:
            continue
        back = r["account"] == main if r["kind"] == "account_credit" else r["account"] != main
        if back:
            r["extra"]["moved_back"] = True


# ---- refunds -------------------------------------------------------------------

def match_refunds(rows: list[dict]) -> None:
    """Pair each refund with the purchase it undoes; the refund joins that purchase's category."""
    purchases = [r for r in rows if r["direction"] == "out" and r["kind"] == "card_purchase"]
    used: set[str] = set()
    for r in sorted((r for r in rows if is_refund(r)), key=_at):
        r["extra"]["refund"] = True
        p = _purchase_for(r, purchases, used)
        if not p:
            continue
        used.add(p["id"])
        r["extra"]["refund_of"] = p["id"]
        p["extra"].setdefault("refunded_by", r["id"])
        if r["category_source"] != "manual":
            r["category"], r["category_source"] = p["category"], p["category_source"]
        if r["extra"].get("merchant_unknown"):  # "Card refund" alerts name no shop: borrow the purchase's
            for k in ("merchant", "merchant_key", "merchant_raw"):
                r[k] = p[k]


def _purchase_for(r: dict, purchases: list[dict], used: set[str]) -> dict | None:
    """Closest earlier unused purchase at the same merchant for the same or a larger amount."""
    at, amount, unknown = _at(r), r["amount_base"], r["extra"].get("merchant_unknown")
    window = [p for p in purchases
              if timedelta(0) <= at - _at(p) <= timedelta(days=REFUND_DAYS)
              and (p["merchant_key"] == r["merchant_key"] or unknown)
              and (not unknown or not (p["account"] and r["account"]) or p["account"] == r["account"])]
    fresh = [p for p in window if p["id"] not in used]
    closest = lambda ps: max(ps, key=_at) if ps else None  # noqa: E731
    exact = [p for p in fresh if abs(p["amount_base"] - amount) < 0.005]
    if unknown:
        return closest(exact)
    found = closest(exact) or closest([p for p in fresh if p["amount_base"] >= amount - 0.005])
    if not found and r["extra"].get("via"):
        # A pay-later refund can return several instalments at once, so no single charge is as large.
        # It is still the same order's money coming back: take the order's latest charge.
        via = [p for p in window if p["extra"].get("via") == r["extra"]["via"]]
        order = [p for p in via if same_order(p["extra"].get("order", ""), r["extra"].get("order", ""))]
        found = closest(order or via)
    return found


# ---- transfers that cancel out ----------------------------------------------------

def _name(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _person(r: dict, people: set[str]) -> str:
    """Which person a credit came from: their name is the counterparty or appears in the description."""
    for text in (_name(r["counterparty"]), _name(r["merchant_raw"])):
        for key in sorted(people, key=len, reverse=True):
            if text == key or f" {key} " in f" {text} ":
                return key
    return ""


def settle_transfers(rows: list[dict]) -> None:
    """Mark money sent to a person and received back from them as settled when it nets to zero.

    What comes back without cancelling exactly is a payback: it reduces spending on that
    person (never below what you sent) instead of counting as income.
    """
    sends = [r for r in rows if r["direction"] == "out" and r["kind"] == "transfer"
             and len(_name(r["counterparty"])) >= 3]
    people = {_name(r["counterparty"]) for r in sends}
    events: dict[str, list[tuple[dict, int]]] = {}
    for r in sends:
        events.setdefault(_name(r["counterparty"]), []).append((r, -_cents(r)))
    for r in rows:
        if r["direction"] == "in" and not is_refund(r) and (key := _person(r, people)):
            events[key].append((r, _cents(r)))
    for evs in events.values():
        evs = [(r, c) for r, c in sorted(evs, key=lambda e: _at(e[0])) if c]
        _cancel(evs)
        _paybacks([(r, c) for r, c in evs if not r["extra"].get("settled")])


def _cancel(evs: list[tuple[dict, int]]) -> None:
    """Group transfers within SETTLE_DAYS of each other that add up to exactly zero."""
    open_: list[tuple[dict, int]] = []
    for r, cents in evs:
        horizon = _at(r) - timedelta(days=SETTLE_DAYS)
        open_ = [(o, c) for o, c in open_ if _at(o) >= horizon][-_MAX_OPEN:]
        hit = next((combo for size in range(1, len(open_) + 1)
                    for combo in combinations(reversed(open_), size) if sum(c for _, c in combo) == -cents), None)
        if not hit:
            open_.append((r, cents))
            continue
        group = [r, *(o for o, _ in hit)]
        gid = "s" + hashlib.sha1("|".join(sorted(g["id"] for g in group)).encode()).hexdigest()[:10]
        for g in group:
            g["extra"]["settled"] = gid
        gone = {o["id"] for o, _ in hit}
        open_ = [(o, c) for o, c in open_ if o["id"] not in gone]


def _paybacks(evs: list[tuple[dict, int]]) -> None:
    """Credits that return part of what was sent earlier (oldest sends first)."""
    pending: list[list] = []  # [row, cents still owed back]
    for r, cents in evs:
        if cents < 0:
            pending.append([r, -cents])
            continue
        horizon, left, first = _at(r) - timedelta(days=SETTLE_DAYS), cents, None
        for p in pending:
            if left and p[1] and horizon <= _at(p[0]) <= _at(r):
                take = min(left, p[1])
                p[1], left, first = p[1] - take, left - take, first or p[0]
        if first:
            r["payback"] = (cents - left) / 100
            r["extra"]["payback"] = True
            r["category"], r["category_source"] = first["category"], first["category_source"]
