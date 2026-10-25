"""SQLite storage, categorization and the learned merchant rules.

Raw emails are kept so the whole ledger can be rebuilt whenever parsers or
rules change: `rebuild()` is cheap and idempotent.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import yaml

from .parsing import BankProfile, RawMessage, Transaction, find_mirrors, parse_message

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_messages (
  id TEXT PRIMARY KEY, date TEXT, sender TEXT, subject TEXT, body TEXT
);
CREATE TABLE IF NOT EXISTS transactions (
  id TEXT PRIMARY KEY, message_id TEXT, bank TEXT, kind TEXT, direction TEXT,
  occurred_at TEXT, month TEXT, amount REAL, currency TEXT, amount_base REAL,
  account TEXT, merchant_raw TEXT, merchant_key TEXT, merchant TEXT,
  counterparty TEXT, status TEXT, pattern TEXT, extra TEXT,
  category TEXT, category_source TEXT, mirror_of TEXT, note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS tx_month ON transactions(month);
-- amount 0 means "any amount"; otherwise the rule only matches that exact amount.
CREATE TABLE IF NOT EXISTS merchant_rules (
  merchant_key TEXT, amount REAL NOT NULL DEFAULT 0, category TEXT, direction TEXT, created_at TEXT,
  PRIMARY KEY (merchant_key, amount)
);
CREATE TABLE IF NOT EXISTS overrides (
  transaction_id TEXT PRIMARY KEY, category TEXT, direction TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS custom_categories (
  key TEXT PRIMARY KEY, name TEXT, color TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS budgets (
  category TEXT PRIMARY KEY, monthly REAL
);
"""


class Categories:
    def __init__(self, spec: dict):
        self.base_currency = spec.get("base_currency", "AED")
        self.fx = {k.upper(): float(v) for k, v in spec.get("fx", {}).items()}
        self.items = spec["categories"]
        self.by_key = {c["key"]: c for c in self.items}
        # Whole-word matching so "rta" never matches inside "Martahan".
        self._res = [
            (c["key"], re.compile(r"(?<![a-z0-9])(?:" + "|".join(
                re.escape(k.strip().lower()) for k in c["keywords"] if k.strip()) + r")(?![a-z0-9])"))
            for c in self.items if any(k.strip() for k in c.get("keywords", []))
        ]

    @classmethod
    def load(cls, *paths: Optional[Path]) -> "Categories":
        for p in reversed(paths):
            if p and p.is_file():
                return cls(yaml.safe_load(p.read_text()))
        raise FileNotFoundError("no categories.yaml found")

    def add(self, key: str, name: str, color: str) -> dict:
        """Add a user category (no keywords: it is filled through corrections). Kept just above "Other"."""
        item = {"key": key, "name": name, "color": color, "keywords": [], "custom": True}
        at = next((i for i, c in enumerate(self.items) if c["key"] == "other"), len(self.items))
        self.items.insert(at, item)
        self.by_key[key] = item
        return item

    def remove(self, key: str) -> None:
        self.items = [c for c in self.items if c["key"] != key]
        self.by_key.pop(key, None)

    def to_base(self, amount: float, currency: str) -> float:
        return round(amount * self.fx.get(currency.upper(), 1.0), 2)

    def match(self, t: Transaction) -> Optional[str]:
        for key, rx in self._res:
            if rx.search(t.merchant_key):
                return key
        return None


class Store:
    def __init__(self, path: Path, banks: list[BankProfile], categories: Categories):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._migrate()
        self.db.executescript(SCHEMA)
        self.banks = banks
        self.categories = categories
        for r in self.db.execute("SELECT * FROM custom_categories ORDER BY created_at"):
            if r["key"] not in categories.by_key:
                categories.add(r["key"], r["name"], r["color"])

    def _migrate(self) -> None:
        cols = [r[1] for r in self.db.execute("PRAGMA table_info(merchant_rules)")]
        if cols and "amount" not in cols:  # v0.1 rules were merchant-wide only
            with self.db:
                self.db.execute("ALTER TABLE merchant_rules RENAME TO merchant_rules_v1")
                self.db.executescript(SCHEMA)
                self.db.execute("INSERT INTO merchant_rules (merchant_key, category, direction, created_at)"
                                " SELECT merchant_key, category, direction, created_at FROM merchant_rules_v1")
                self.db.execute("DROP TABLE merchant_rules_v1")

    # ---- ingestion -------------------------------------------------------

    def add_messages(self, messages: Iterable[RawMessage]) -> int:
        cur = self.db.executemany(
            "INSERT OR IGNORE INTO raw_messages VALUES (?,?,?,?,?)",
            [(m.id, m.date, m.sender, m.subject, m.body) for m in messages],
        )
        self.db.commit()
        return cur.rowcount

    def source(self) -> dict:
        n, first, last = self.db.execute("SELECT count(*), min(date), max(date) FROM raw_messages").fetchone()
        return {"emails": n, "first": first, "last": last}

    def latest_message_date(self) -> Optional[str]:
        row = self.db.execute("SELECT max(date) FROM raw_messages").fetchone()
        return row[0]

    def rebuild(self) -> dict:
        """Re-parse every stored email and re-apply rules and overrides."""
        msgs = [RawMessage(**dict(r)) for r in self.db.execute("SELECT * FROM raw_messages")]
        txns = [t for t in (parse_message(m, self.banks) for m in msgs) if t]
        mirrors = find_mirrors(txns, self.banks)
        rules = {(r["merchant_key"], r["amount"]): r for r in self.db.execute("SELECT * FROM merchant_rules")}
        overrides = {r["transaction_id"]: r for r in self.db.execute("SELECT * FROM overrides")}

        rows = []
        for t in txns:
            rule = rules.get((t.merchant_key, round(t.amount, 2))) or rules.get((t.merchant_key, 0))
            category, source, direction = self._categorize(t, rule)
            o = overrides.get(t.id)
            note = ""
            if o:
                category = o["category"] or category
                direction = o["direction"] or direction
                source = "manual" if (o["category"] or o["direction"]) else source
                note = o["note"] or ""
            rows.append((
                t.id, t.message_id, t.bank, t.kind, direction, t.occurred_at, t.occurred_at[:7],
                t.amount, t.currency, self.categories.to_base(t.amount, t.currency), t.account,
                t.merchant_raw, t.merchant_key, t.merchant, t.counterparty, t.status, t.pattern,
                json.dumps(t.extra), category, source, mirrors.get(t.id), note,
            ))
        with self.db:
            self.db.execute("DELETE FROM transactions")
            self.db.executemany(
                f"INSERT INTO transactions VALUES ({','.join('?' * 22)})", rows)
        return {"messages": len(msgs), "transactions": len(txns), "mirrors": len(mirrors),
                "unparsed": len(msgs) - len(txns)}

    def _categorize(self, t: Transaction, rule) -> tuple[str, str, str]:
        direction = t.direction
        if rule:
            direction = rule["direction"] or direction
            if rule["category"]:
                return rule["category"], "learned", direction
        if direction == "in" and t.kind in ("account_credit",):
            return self.categories.match(t) or "income", "rule", direction
        hit = self.categories.match(t)
        if hit:
            return hit, "rule", direction
        if t.kind == "transfer" and t.counterparty:
            return "people", "rule", direction
        return "other", "default", direction

    # ---- user corrections --------------------------------------------------

    def correct(self, tx_id: str, category: Optional[str] = None, direction: Optional[str] = None,
                note: Optional[str] = None, remember: bool = True, match_amount: bool = False) -> None:
        """Fix one transaction. With remember=True the fix becomes a rule for its merchant,
        so every past and future transaction from that merchant follows it. With
        match_amount=True the rule only covers that merchant at this exact amount
        (e.g. the AED 32.50 Careem Food order that is always your coffee)."""
        row = self.db.execute("SELECT merchant_key, amount FROM transactions WHERE id=?", (tx_id,)).fetchone()
        if not row:
            raise KeyError(tx_id)
        amount = round(row["amount"], 2) if match_amount else 0
        with self.db:
            if remember and (category or direction):
                prev = self.db.execute("SELECT * FROM merchant_rules WHERE merchant_key=? AND amount=?",
                                       (row["merchant_key"], amount)).fetchone()
                self.db.execute(
                    "INSERT OR REPLACE INTO merchant_rules (merchant_key, amount, category, direction, created_at)"
                    " VALUES (?,?,?,?,?)",
                    (row["merchant_key"], amount, category or (prev and prev["category"]),
                     direction or (prev and prev["direction"]), datetime.now().isoformat()))
                # A merchant-wide rule supersedes any one-off override on this transaction.
                self.db.execute("UPDATE overrides SET category=NULL, direction=NULL WHERE transaction_id=?",
                                (tx_id,))
            if not remember or note is not None:
                prev = self.db.execute("SELECT * FROM overrides WHERE transaction_id=?", (tx_id,)).fetchone()
                self.db.execute(
                    "INSERT OR REPLACE INTO overrides VALUES (?,?,?,?)",
                    (tx_id,
                     (category if not remember else None) or (prev and prev["category"]),
                     (direction if not remember else None) or (prev and prev["direction"]),
                     note if note is not None else (prev and prev["note"])))
        self.rebuild()

    def rules(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT r.*, (SELECT merchant FROM transactions t WHERE t.merchant_key=r.merchant_key LIMIT 1)"
            " AS merchant FROM merchant_rules r ORDER BY created_at DESC")]

    def delete_rule(self, key: str, amount: float = 0) -> None:
        with self.db:
            self.db.execute("DELETE FROM merchant_rules WHERE merchant_key=? AND amount=?", (key, round(amount, 2)))
        self.rebuild()

    def add_category(self, name: str, color: str = "gray") -> dict:
        name = re.sub(r"\s+", " ", name).strip()
        if not name:
            raise ValueError("name is required")
        if any(c["name"].lower() == name.lower() for c in self.categories.items):
            raise ValueError(f"a category called {name!r} already exists")
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "category"
        key, n = base, 2
        while key in self.categories.by_key:
            key, n = f"{base}-{n}", n + 1
        with self.db:
            self.db.execute("INSERT INTO custom_categories VALUES (?,?,?,?)",
                            (key, name, color, datetime.now().isoformat()))
        return self.categories.add(key, name, color)

    def delete_category(self, key: str) -> None:
        """Remove a user category; its transactions fall back to the built-in rules."""
        if not self.categories.by_key.get(key, {}).get("custom"):
            raise KeyError(key)
        with self.db:
            self.db.execute("DELETE FROM custom_categories WHERE key=?", (key,))
            self.db.execute("DELETE FROM merchant_rules WHERE category=? AND direction IS NULL", (key,))
            self.db.execute("UPDATE merchant_rules SET category=NULL WHERE category=?", (key,))
            self.db.execute("UPDATE overrides SET category=NULL WHERE category=?", (key,))
            self.db.execute("DELETE FROM budgets WHERE category=?", (key,))
        self.categories.remove(key)
        self.rebuild()

    def set_budget(self, category: str, monthly: Optional[float]) -> None:
        with self.db:
            if monthly is None or monthly <= 0:
                self.db.execute("DELETE FROM budgets WHERE category=?", (category,))
            else:
                self.db.execute("INSERT OR REPLACE INTO budgets VALUES (?,?)", (category, monthly))

    # ---- queries -------------------------------------------------------------

    _VISIBLE = "mirror_of IS NULL"

    def transactions(self, month: Optional[str] = None, category: Optional[str] = None,
                     q: Optional[str] = None, internal: str = "show", limit: int = 500) -> list[dict]:
        """internal: "show" everything, "hide" or "only" moves between your own accounts."""
        sql, args = f"SELECT * FROM transactions WHERE {self._VISIBLE}", []
        if internal == "hide":
            sql += " AND direction!='internal'"
        elif internal == "only":
            sql += " AND direction='internal'"
        if month:
            sql += " AND month=?"; args.append(month)
        if category:
            sql += " AND category=?"; args.append(category)
        if q:
            sql += " AND (merchant LIKE ? OR counterparty LIKE ? OR note LIKE ?)"; args += [f"%{q}%"] * 3
        sql += " ORDER BY occurred_at DESC LIMIT ?"; args.append(limit)
        out = []
        for r in self.db.execute(sql, args):
            d = dict(r); d["extra"] = json.loads(d["extra"] or "{}"); out.append(d)
        return out

    def months(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            f"SELECT month, round(sum(CASE WHEN direction='out' THEN amount_base ELSE 0 END),2) AS spent,"
            f" round(sum(CASE WHEN direction='in' THEN amount_base ELSE 0 END),2) AS received,"
            f" count(*) AS count FROM transactions WHERE {self._VISIBLE} GROUP BY month ORDER BY month")]

    def summary(self, month: str) -> dict:
        v = self._VISIBLE
        def q(sql, *a):
            return [dict(r) for r in self.db.execute(sql, (month, *a))]
        by_cat = q(f"SELECT category, round(sum(amount_base),2) AS total, count(*) AS count FROM transactions"
                   f" WHERE month=? AND direction='out' AND {v} GROUP BY category ORDER BY total DESC")
        by_day = q(f"SELECT substr(occurred_at,1,10) AS day, round(sum(amount_base),2) AS total FROM transactions"
                   f" WHERE month=? AND direction='out' AND {v} GROUP BY day ORDER BY day")
        merchants = q(f"SELECT merchant, category, round(sum(amount_base),2) AS total, count(*) AS count"
                      f" FROM transactions WHERE month=? AND direction='out' AND {v}"
                      f" GROUP BY merchant_key ORDER BY total DESC LIMIT 8")
        by_hour = q(f"SELECT CAST(substr(occurred_at,12,2) AS INT) AS hour, round(sum(amount_base),2) AS total"
                    f" FROM transactions WHERE month=? AND direction='out' AND {v} GROUP BY hour")
        tot = q(f"SELECT round(coalesce(sum(CASE WHEN direction='out' THEN amount_base END),0),2) AS spent,"
                f" round(coalesce(sum(CASE WHEN direction='in' THEN amount_base END),0),2) AS received,"
                f" round(coalesce(sum(CASE WHEN direction='internal' THEN amount_base END),0),2) AS moved,"
                f" sum(direction!='internal') AS count, coalesce(sum(category_source='default' AND direction='out'),0) AS uncategorized"
                f" FROM transactions WHERE month=? AND {v}")[0]
        prev = self.db.execute(
            f"SELECT round(coalesce(sum(amount_base),0),2) FROM transactions WHERE month=? AND direction='out' AND {v}",
            (_prev_month(month),)).fetchone()[0]
        biggest = q(f"SELECT merchant, category, amount_base, occurred_at FROM transactions"
                    f" WHERE month=? AND direction='out' AND {v} ORDER BY amount_base DESC LIMIT 1")
        budgets = {r["category"]: r["monthly"] for r in self.db.execute("SELECT * FROM budgets")}
        return {"month": month, "currency": self.categories.base_currency, **tot, "previous_spent": prev,
                "by_category": by_cat, "by_day": by_day, "top_merchants": merchants,
                "by_hour": by_hour, "biggest": biggest[0] if biggest else None, "budgets": budgets}


def _prev_month(month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def transaction_dict(t: Transaction) -> dict:
    return asdict(t)
