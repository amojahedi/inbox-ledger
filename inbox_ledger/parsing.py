"""Turn raw bank emails into transactions using declarative YAML bank profiles.

Adding a bank means adding a YAML file under ``banks/`` — no code changes.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

import yaml

from .merchants import merchant_key, display_name


@dataclass
class RawMessage:
    id: str
    date: str  # ISO 8601, UTC
    sender: str
    subject: str
    body: str


@dataclass
class Transaction:
    id: str
    message_id: str
    bank: str
    kind: str
    direction: str  # out | in | internal
    occurred_at: str  # local ISO timestamp, no offset
    amount: float  # in original currency, always positive
    currency: str
    account: str
    merchant_raw: str
    merchant_key: str
    merchant: str
    counterparty: str = ""
    status: str = ""
    pattern: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class Pattern:
    name: str
    kind: str
    direction: str
    regex: re.Pattern
    when_format: Optional[str | list] = None
    when_regex: Optional[re.Pattern] = None
    transfer_directions: dict = field(default_factory=dict)
    failed_statuses: list = field(default_factory=list)
    subject_regex: Optional[re.Pattern] = None  # extra named groups taken from the subject line
    label: str = ""  # merchant shown when the alert names none


@dataclass
class BankProfile:
    name: str
    senders: list[re.Pattern]
    timezone: ZoneInfo
    patterns: list[Pattern]
    gmail_query: str = ""
    dedupe: dict = field(default_factory=dict)
    status: str = ""  # verified | beta (informational)
    fallback: bool = False  # tried only after every bank-specific profile

    def handles(self, sender: str) -> bool:
        return any(s.search(sender.lower()) for s in self.senders)


def load_bank(path: Path) -> BankProfile:
    spec = yaml.safe_load(path.read_text())
    patterns = [
        Pattern(
            name=p["name"],
            kind=p["kind"],
            direction=p.get("direction", "out"),
            regex=re.compile(p["regex"], re.S),
            when_format=p.get("when_format"),
            when_regex=re.compile(p["when_regex"]) if p.get("when_regex") else None,
            transfer_directions=p.get("transfer_directions", {}),
            failed_statuses=[s.lower() for s in p.get("failed_statuses", [])],
            subject_regex=re.compile(p["subject_regex"]) if p.get("subject_regex") else None,
            label=p.get("label", ""),
        )
        for p in spec["patterns"]
    ]
    return BankProfile(
        name=spec["name"],
        senders=[re.compile(s, re.I) for s in spec.get("senders", [])],
        timezone=ZoneInfo(spec.get("timezone", "UTC")),
        patterns=patterns,
        gmail_query=spec.get("gmail_query", ""),
        dedupe=spec.get("dedupe", {}),
        status=str(spec.get("status", "")),
        fallback=bool(spec.get("fallback", False)),
    )


def load_banks(*dirs: Path) -> list[BankProfile]:
    """Later directories override earlier ones file-by-file (user config over defaults)."""
    files: dict[str, Path] = {}
    for d in dirs:
        if d and d.is_dir():
            for f in sorted(d.glob("*.y*ml")):
                files[f.stem] = f
    return sorted((load_bank(f) for f in files.values()), key=lambda b: b.fallback)  # stable: fallbacks last


def _amount(text: str) -> float:
    return float(text.replace(",", ""))


# Tried after a pattern's own when_format, so most profiles can omit it.
COMMON_WHEN = [
    f"{d}{t}" for d in ("%d-%b-%Y", "%d/%b/%Y", "%d %b %Y", "%d-%b-%y", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y",
                        "%Y-%m-%d")
    for t in (" %I:%M:%S %p", " %I:%M %p", " %H:%M:%S", " %H:%M", "")
]


def _parse_when(when: str, formats) -> Optional[datetime]:
    when = re.sub(r"(\d)\s*([AaPp][Mm])", r"\1 \2", re.sub(r"\s*,\s*|\s+", " ", when)).strip()
    declared = [formats] if isinstance(formats, str) else list(formats or [])
    for fmt in declared + COMMON_WHEN:
        try:
            return datetime.strptime(when, fmt)
        except ValueError:
            continue
    return None


def _local_time(msg: RawMessage, bank: BankProfile, pattern: Pattern, groups: dict) -> str:
    when = groups.get("when")
    if not when and pattern.when_regex:
        m = pattern.when_regex.search(msg.body)
        when = m.group("when") if m else None
    parsed = _parse_when(when, pattern.when_format) if when else None
    if parsed:
        return parsed.isoformat(timespec="minutes")
    sent = datetime.fromisoformat(msg.date.replace("Z", "+00:00"))
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)
    return sent.astimezone(bank.timezone).replace(tzinfo=None).isoformat(timespec="minutes")


def _clean(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", text or "").strip(" .|")


def parse_message(msg: RawMessage, banks: Iterable[BankProfile]) -> Optional[Transaction]:
    body = _clean(msg.body)
    for bank in sorted(banks, key=lambda b: b.fallback):  # bank-specific profiles win over fallbacks
        if not bank.handles(msg.sender):
            continue
        for p in bank.patterns:
            m = p.regex.search(body)
            if not m:
                continue
            g = {k: v for k, v in m.groupdict().items() if v is not None}
            if p.subject_regex and (sm := p.subject_regex.search(msg.subject or "")):
                for k, v in sm.groupdict().items():
                    if v is not None:
                        g.setdefault(k, v)
            status = _clean(g.get("status"))
            if status.lower() in p.failed_statuses:
                return None
            direction = p.direction
            transfer_type = _clean(g.get("transfer_type"))
            if transfer_type in p.transfer_directions:
                direction = p.transfer_directions[transfer_type]
            counterparty = _clean(g.get("counterparty"))
            raw = _clean(g.get("merchant")) or counterparty or transfer_type or p.label or p.name
            key = merchant_key(raw)
            extra = {"transfer_type": transfer_type} if transfer_type else {}
            if p.kind == "card_purchase" and direction == "in" and not _clean(g.get("merchant")):
                extra["merchant_unknown"] = True  # a refund that names no shop: matched by amount instead
            return Transaction(
                id=hashlib.sha1(f"{bank.name}:{msg.id}".encode()).hexdigest()[:16],
                message_id=msg.id,
                bank=bank.name,
                kind=p.kind,
                direction=direction,
                occurred_at=_local_time(msg, bank, p, g),
                amount=_amount(g["amount"]),
                currency=g.get("currency", "AED"),
                account=g.get("last4", ""),
                merchant_raw=raw,
                merchant_key=key,
                merchant=display_name(raw),
                counterparty=counterparty,
                status=status,
                pattern=p.name,
                extra=extra,
            )
    return None


def find_mirrors(txns: list[Transaction], banks: Iterable[BankProfile]) -> dict[str, str]:
    """Map duplicate transaction id -> id of the primary record it mirrors.

    Banks often send two emails for one movement (e.g. a transfer receipt and an
    account-debit alert). The richer one is kept; the mirror is hidden.
    """
    rules = {b.name: b.dedupe for b in banks if b.dedupe}
    mirrors: dict[str, str] = {}
    used: set[str] = set()
    for t in txns:
        rule = rules.get(t.bank)
        if not rule or t.kind not in rule.get("mirror_kinds", []):
            continue
        window = float(rule.get("window_hours", 6)) * 3600
        t_at = datetime.fromisoformat(t.occurred_at)
        best = None
        for p in txns:
            if (p.bank != t.bank or p.kind != rule.get("primary_kind") or p.id in used
                    or (p.account != t.account and not rule.get("ignore_account"))
                    or abs(p.amount - t.amount) > 0.005):
                continue
            gap = abs((datetime.fromisoformat(p.occurred_at) - t_at).total_seconds())
            if gap <= window and (best is None or gap < best[0]):
                best = (gap, p)
        if best:
            mirrors[t.id] = best[1].id
            used.add(best[1].id)
    return mirrors
