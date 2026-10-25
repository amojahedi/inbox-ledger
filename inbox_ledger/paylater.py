"""Buy-now-pay-later support: explain "Tabby" card charges with the real store.

A pay-later provider charges your card once per instalment, so the bank alert only
names the provider. The provider's own emails name the store and order and arrive
seconds after the charge. We parse those emails into events, pair each card charge
with the event of the same amount closest in time, and re-label the charge.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

import yaml

from .merchants import display_name, merchant_key
from .parsing import RawMessage, Transaction

PAYMENT_KINDS = ("purchase", "payment", "final", "consolidated")


@dataclass
class Event:
    message_id: str
    provider: str
    kind: str
    at: datetime  # UTC
    store: str = ""
    order: str = ""
    paid: float = 0.0
    remaining: Optional[float] = None
    total: Optional[float] = None
    refunded: Optional[float] = None
    instalments: Optional[int] = None
    next_due: str = ""
    full_refund: bool = False
    items: list = field(default_factory=list)  # [(store, amount)] for itemised receipts


@dataclass
class Provider:
    name: str
    senders: list[re.Pattern]
    card_merchant: str
    match_minutes: float
    gmail_query: str
    events: list[dict] = field(default_factory=list)

    def handles(self, sender: str) -> bool:
        return any(s.search(sender.lower()) for s in self.senders)


def load_provider(path: Path) -> Provider:
    spec = yaml.safe_load(path.read_text())
    amount = spec.get("amount", "")
    events = []
    for e in spec["events"]:
        events.append({
            "kind": e["kind"],
            "when": re.compile(e["when"], re.I),
            "store": [re.compile(p.replace("{amount}", amount), re.S) for p in e.get("store", [])],
            "fields": {k: re.compile(v.replace("{amount}", amount), re.S) for k, v in e.get("fields", {}).items()},
            "count": re.compile(e["count_instalments"]) if e.get("count_instalments") else None,
            "items_after": re.compile(e["items_after"]) if e.get("items_after") else None,
            "item": re.compile(e["item"]) if e.get("item") else None,
            "item_store": [re.compile(p) for p in e.get("item_store", [])],
        })
    return Provider(spec["name"], [re.compile(s, re.I) for s in spec["senders"]], spec["card_merchant"],
                    float(spec.get("match_minutes", 30)), spec.get("gmail_query", ""), events)


def load_providers(*dirs: Optional[Path]) -> list[Provider]:
    files: dict[str, Path] = {}
    for d in dirs:
        if d and d.is_dir():
            for f in sorted(d.glob("*.y*ml")):
                files[f.stem] = f
    return [load_provider(f) for f in files.values()]


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_event(msg: RawMessage, providers: Iterable[Provider]) -> Optional[Event]:
    for p in providers:
        if not p.handles(msg.sender):
            continue
        text = f"{msg.subject}\n{msg.body}"
        for spec in p.events:
            if not spec["when"].search(text):
                continue
            at = datetime.fromisoformat(msg.date.replace("Z", "+00:00"))
            ev = Event(msg.id, p.name, spec["kind"], at if at.tzinfo else at.replace(tzinfo=timezone.utc))
            for rx in spec["store"]:
                m = rx.search(msg.body)
                if m:
                    ev.store = re.sub(r"\s+", " ", m.group("v")).strip(" .|")
                    break
            for name, rx in spec["fields"].items():
                m = rx.search(msg.body)
                if not m:
                    continue
                if name == "full_refund":
                    ev.full_refund = True
                    continue
                v = m.group("v").strip()
                if name in ("order", "next_due"):
                    setattr(ev, name, v)
                else:
                    setattr(ev, name, _num(v))
            if spec["count"]:
                ev.instalments = len(spec["count"].findall(msg.body)) + 1
            if spec["item"] and spec["items_after"]:
                start = spec["items_after"].search(msg.body)
                for m in spec["item"].finditer(msg.body, start.end() if start else len(msg.body)):
                    label = m.group("label").strip()
                    store = next((x.group("v") for x in (r.search(label) for r in spec["item_store"]) if x), label)
                    ev.items.append((store, _num(m.group("v"))))
            if ev.kind in PAYMENT_KINDS and not ev.paid:
                return None
            return ev
    return None


def same_order(a: str, b: str) -> bool:
    """Purchase emails truncate long order ids, so compare by prefix."""
    a, b = a.lstrip("#").lower(), b.lstrip("#").lower()
    return bool(a and b) and (a == b or (min(len(a), len(b)) >= 8 and (a.startswith(b) or b.startswith(a))))


def attach(txns: list[Transaction], events: list[Event], providers: list[Provider],
           tz_for_bank: dict[str, ZoneInfo]) -> dict[str, str]:
    """Re-label provider card charges with the store from the matching email.

    Returns {event message id: transaction id} for the pairs it made.
    """
    by_provider = {p.name: p for p in providers}
    pairs: dict[str, str] = {}
    parts: list[tuple[Transaction, list]] = []
    used: set[str] = set()
    for t in sorted(list(txns), key=lambda t: t.occurred_at):
        p = next((p for p in providers if t.direction == "out" and t.merchant_key.startswith(p.card_merchant)), None)
        if not p:
            continue
        tz = tz_for_bank.get(t.bank, ZoneInfo("UTC"))
        t_at = datetime.fromisoformat(t.occurred_at).replace(tzinfo=tz)
        best = None
        for e in events:
            if (e.provider != p.name or e.kind not in PAYMENT_KINDS or e.message_id in used
                    or abs(e.paid - t.amount) > 0.005):
                continue
            gap = abs((e.at - t_at).total_seconds())
            if gap <= by_provider[e.provider].match_minutes * 60 and (best is None or gap < best[0]):
                best = (gap, e)
        if not best:
            t.extra["via"] = p.name
            t.merchant, t.merchant_key = p.name, p.card_merchant  # "Tabby, 800…" -> "Tabby"
            continue
        e = best[1]
        used.add(e.message_id)
        pairs[e.message_id] = t.id
        t.extra.update({"via": p.name, "bnpl": e.kind})
        if e.order:
            t.extra["order"] = e.order
        if e.store:
            _relabel(t, e.store)
        elif e.items and abs(sum(a for _, a in e.items) - t.amount) < 0.05:
            parts.append((t, e.items))
        elif e.kind == "consolidated":
            t.merchant = f"{p.name} (several orders)"
    for t, items in parts:  # one charge paid several orders: split it so each part counts under its store
        i = txns.index(t)
        pieces = []
        for n, (store, amount) in enumerate(items, 1):
            piece = replace(t, id=f"{t.id}-{n}", amount=amount, extra={**t.extra, "part": f"{n}/{len(items)}"})
            _relabel(piece, store)
            pieces.append(piece)
        txns[i:i + 1] = pieces
    return pairs


def _relabel(t: Transaction, store: str) -> None:
    t.merchant_raw = store
    t.merchant_key = merchant_key(store, location=False)  # store names carry no "<city> <CC>" suffix
    t.merchant = display_name(store, location=False)


def open_orders(events: list[Event], until: datetime) -> list[dict]:
    """What is still owed per order as of `until`, from the latest event of each order."""
    orders: list[dict] = []
    for e in sorted((e for e in events if e.at <= until and e.order), key=lambda e: e.at):
        o = next((o for o in orders if o["provider"] == e.provider and same_order(o["order"], e.order)), None)
        if o is None:
            o = {"provider": e.provider, "order": e.order, "store": e.store, "remaining": None, "paid": 0.0,
                 "total": None, "instalments": None, "last_paid": None, "next_due": ""}
            orders.append(o)
        if len(e.order) > len(o["order"]):
            o["order"] = e.order
        o["store"] = o["store"] or e.store
        if e.total and e.kind == "purchase":
            o["total"], o["instalments"] = e.total, e.instalments
        elif e.total and e.kind == "update":
            o["total"] = e.total
        if e.kind in PAYMENT_KINDS:
            o["paid"] += e.paid
            o["last_paid"] = e.at
        if e.kind == "final":
            o["remaining"] = 0.0
        elif e.remaining is not None:
            o["remaining"] = e.remaining
        if e.kind == "refund" and e.full_refund:
            o["remaining"] = 0.0  # a partial refund is reflected by the next payment's "Total due"
        o["next_due"] = e.next_due or o["next_due"]
    return [o for o in orders if o["remaining"]]
