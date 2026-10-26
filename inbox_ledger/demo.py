"""Synthetic Emirates NBD-style alert emails for the demo ledger. Every name and number is invented."""
from __future__ import annotations

import calendar
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from .parsing import RawMessage

ALERTS = "alert@emiratesnbd.com"
ONLINE = "OnlineBanking@emiratesnbd.com"
CARD, MAIN, SAVINGS = "4021", "7710", "3390"
UAE_OFFSET = timedelta(hours=4)

SALARY = 30000.00
RENT = 8000.00
SAVING_TRANSFER = 8000.00
LANDLORD = "LANDLORD"
FRIENDS = ["SARA AHMED", "LAYLA HASSAN", "DANIEL ROSS", "PRIYA MENON", "YUSUF RAHMAN", "NOUR KHALIL"]

# Monthly spending per category (AED). Each month lands within a few percent of these, so months
# compare sensibly and the demo's budgets (DEMO_BUDGETS) sit just above typical spending.
TARGETS = {"dining": 1250, "coffee": 850, "groceries": 650, "shopping": 450, "health": 250,
           "taxi": 200, "transport": 100, "entertainment": 100, "other": 120}

# (merchant as printed on the card, relative size, purchases per month, likely hours, category it counts toward)
_LUNCH, _DINNER, _DAY, _EVENING = (12, 14), (19, 22), (9, 18), (17, 22)
_CARD_MERCHANTS = [
    ("CAREEM FOOD DUBAI AE", 1.0, (6, 9), _DINNER, "dining"),
    ("TALABAT DUBAI AE", 1.3, (4, 6), _DINNER, "dining"),
    ("THE MEAT CO RESTAURANT DUBAI AE", 3.5, (0, 1), _DINNER, "dining"),
    ("SHAWARMA HOUSE DUBAI AE", 0.5, (2, 4), _LUNCH, "dining"),
    ("ARABICA DUBAI AE", 1.0, (8, 11), (9, 17), "coffee"),
    ("STARBUCKS DUBAI AE", 0.8, (4, 6), (8, 11), "coffee"),
    ("TIM HORTONS DUBAI AE", 0.6, (2, 4), (7, 11), "coffee"),
    ("CARIBOU COFFEE DUBAI AE", 0.7, (1, 2), (9, 17), "coffee"),
    ("CARREFOUR MOE DUBAI AE", 1.0, (2, 4), _EVENING, "groceries"),
    ("SPINNEYS DUBAI AE", 1.3, (1, 2), _EVENING, "groceries"),
    ("OUNASS DUBAI AE", 2.5, (0, 1), (12, 22), "shopping"),
    ("6TH STREET DUBAI AE", 1.5, (1, 1), (12, 22), "shopping"),
    ("AMAZON.AE DUBAI AE", 1.0, (1, 2), (10, 23), "shopping"),
    ("NAMSHI DUBAI AE", 1.2, (0, 1), (10, 23), "shopping"),
    ("LIFE PHARMACY DUBAI AE", 0.6, (0, 1), _DAY, "health"),
    ("SEPHORA DUBAI AE", 1.2, (0, 1), (12, 21), "health"),
    ("F45 TRAINING DUBAI AE", 0.5, (1, 2), (6, 8), "health"),
    ("CAREEM RIDE DUBAI AE", 1.0, (4, 7), (7, 23), "taxi"),
    ("SALIK DUBAI AE", 1.0, (1, 1), _DAY, "transport"),
    ("ENOC DUBAI AE", 1.5, (0, 1), _DAY, "transport"),
    ("VOX CINEMAS DUBAI AE", 1.0, (1, 2), _EVENING, "entertainment"),
    # Not in categories.yaml on purpose: these are what you teach the app once.
    ("AL FARIS TAILORING DUBAI AE", 1.5, (1, 1), _DAY, "other"),
    ("GOLDEN SANDS TRADING LLC DUBAI AE", 1.0, (0, 1), _DAY, "other"),
    ("ZEN CORNER 1182 DUBAI AE", 0.6, (0, 1), _EVENING, "other"),
]
# (merchant, amount, day of month, hour, currency) — fixed monthly charges
_RECURRING = [
    ("FITNESS FIRST DUBAI AE", 349.00, 3, 7, "AED"),
    ("DEWA DUBAI AE", None, 5, 10, "AED"),
    ("NETFLIX.COM SINGAPORE SG", 15.49, 8, 3, "USD"),
    ("SPOTIFY LUXEMBOURG LU", 4.99, 12, 5, "USD"),
    ("APPLE.COM/BILL DUBLIN IE", 9.99, 15, 6, "USD"),
    ("OPENAI *CHATGPT SUBSCR SAN FRANCISCO US", 20.00, 19, 4, "USD"),
    ("DU DUBAI AE", 449.00, 21, 11, "AED"),
    ("ETISALAT DUBAI AE", 389.00, 18, 10, "AED"),
]


def _fmt(amount: float) -> str:
    return f"{amount:,.2f}"


def _iso(local: datetime) -> str:
    return (local - UAE_OFFSET).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp(rng: random.Random, year: int, month: int, day: int, hours: tuple[int, int]) -> datetime:
    return datetime(year, month, day, rng.randint(*hours) % 24, rng.randint(0, 59), rng.randint(0, 59))


def _card(rng: random.Random, local: datetime, merchant: str, amount: float, currency: str) -> tuple:
    when = local.strftime("%d-%b-%Y %I:%M %p")
    body = (f"Dear Customer, Purchase of {currency} {_fmt(amount)} with Debit Card ending {CARD} at {merchant} "
            f"on {when}. Avl Bal AED {_fmt(rng.uniform(900, 9200))}")
    return local, ALERTS, "Card transaction alert", body


def _masked(account: str) -> str:
    return f"012XXX{account[:2]}XXX{account[2:]}"


def _advice(local: datetime, account: str, text: str) -> tuple:
    """An account 'Transaction advice' alert; the account's last 4 digits are only in the subject."""
    return (local, ALERTS, f"Transaction advice for your account ending with {account}",
            f"Dear Customer, {text.format(acct=_masked(account))}")


def _atm(rng: random.Random, local: datetime) -> tuple:
    amount = float(rng.choice([100, 200, 200, 300]))
    return _advice(local, MAIN, f"AED {_fmt(amount)} has been withdrawn from your account {{acct}}. The available "
                                f"balance is AED {_fmt(rng.uniform(900, 9200))}. Save queuing time by using our "
                                f"free ATMs 24 x 7.")


def _transfer(rng: random.Random, local: datetime, kind: str, src: str, to_name: str,
              amount: float) -> list[tuple]:
    """An online-banking transfer notification (ENBD sends no separate debit alert for these)."""
    label = "Local Bank Transfer" if kind == "local" else "Own Account Transfer"
    iban = f"AE07033{rng.randint(10**15, 10**16 - 1)}"
    body = (f"CIF: ***00*** Dear Alex Demo, Here is a consolidated status of your {label}.\n"
            f"Transaction Date:\n{local:%d/%b/%Y %I:%M %p}\nFrom Account:\n012******{src}\n"
            f"Debit Amount:\nAED {_fmt(amount)}\nTransaction Amount:\nAED {_fmt(amount)}\nExchange Rate:\nN/A\n"
            f"Beneficiary Name:\n{to_name}\nBeneficiary Account / IBAN:\n{iban}\nStatus:\nSuccess")
    return [(local, ONLINE, label, body)]


TABBY = "notifications@tabby.ai"
_TABBY_STORES = [("Noon", 320, 600), ("Namshi", 280, 560), ("IKEA", 400, 640)]


def _tabby_order(rng: random.Random, local: datetime, store: str, total: float, n: int = 4) -> list[tuple]:
    """A pay-in-4 order: each instalment is a 'Tabby' card charge plus Tabby's email naming the store."""
    order = f"NA{rng.randint(10**11, 10**12 - 1)}{rng.randint(1000, 9999)}"
    parts = [round(total / n, 2)] * (n - 1)
    parts.append(round(total - sum(parts), 2))
    dates = [local + timedelta(days=30 * i) for i in range(n)]
    sched = "".join(f"| | {d:%-d %b, %Y} |  {_fmt(a)} |\n| | |\n" for d, a in zip(dates[1:], parts[1:]))
    out = []
    for i, (when, amount) in enumerate(zip(dates, parts)):
        out.append(_card(rng, when, "TABBY FZ LLC DUBAI AE", amount, "AED"))
        email_at = when + timedelta(seconds=rng.randint(1, 8))
        if i == 0:
            body = (f" Thanks for choosing Tabby, Alex.\nYour order from {store} is confirmed and the first payment "
                    f"was successful.\n\n| | {store} |\n\n| | Paid today |  {_fmt(amount)} |\n| | |\n{sched}\n"
                    f"| Date of purchase | {when:%-d %b, %Y} |\n| Order number | #{order[:21]} |\n"
                    f"| Total order amount |  {_fmt(total)} |\n\n| Credit summary |\n"
                    f"| Total to be repaid by borrower |  {_fmt(total - amount)} |")
            out.append((email_at, TABBY, f"Successful purchase at {store}", body))
        elif i < n - 1:
            due = sum(parts[i + 1:])
            body = (f" Thanks for your payment\nHere’s your receipt for {store}.\nOrder# {order}\n\n"
                    f"| Paid today |  {_fmt(amount)} |\n\n| Total due |  {_fmt(due)} |\n"
                    f"| Next payment | {dates[i + 1]:%-d %b, %Y} |")
            out.append((email_at, TABBY, "Thanks! Here’s your Tabby payment confirmation.", body))
        else:
            body = (f" Thanks for the last payment\nYou've made all your payments from {store} successfully. "
                    f"Here's your receipt.\nOrder# {order}\n\n| Paid today |  {_fmt(amount)} |\n\n"
                    f"| Total paid |  {_fmt(total)} |")
            out.append((email_at, TABBY, "Thanks! Here’s your Tabby payment confirmation.", body))
    return out


def _month_events(rng: random.Random, year: int, month: int, travel: bool) -> list[tuple]:
    days = calendar.monthrange(year, month)[1]
    out: list[tuple] = []

    # Draw purchases, then scale each category so the month lands near its target (±8%).
    drawn: dict[str, list] = {}
    for merchant, size, (cmin, cmax), hours, group in _CARD_MERCHANTS:
        for _ in range(rng.randint(cmin, cmax)):
            drawn.setdefault(group, []).append([merchant, size * rng.uniform(0.7, 1.3), hours])
    for group, items in drawn.items():
        k = TARGETS[group] * rng.uniform(0.92, 1.08) / sum(i[1] for i in items)
        for merchant, weight, hours in items:
            out.append(_card(rng, _stamp(rng, year, month, rng.randint(1, days), hours), merchant,
                             round(weight * k, 2), "AED"))

    for merchant, amount, day, hour, currency in _RECURRING:
        if amount is None:
            amount = round(rng.uniform(340, 420), 2)
        out.append(_card(rng, _stamp(rng, year, month, day, (hour, hour)), merchant, amount, currency))

    if travel:
        out.append(_card(rng, _stamp(rng, year, month, rng.randint(2, 20), (10, 22)),
                         "EMIRATES DUBAI AE", round(rng.uniform(900, 1400), 2), "AED"))

    if True:  # one small pay-in-4 order a month, so the Pay later card always has something to show
        store, lo, hi = rng.choice(_TABBY_STORES)
        out += _tabby_order(rng, _stamp(rng, year, month, rng.randint(3, min(days, 26)), (11, 21)), store,
                            round(rng.uniform(lo, hi), 2))

    out.append(_advice(_stamp(rng, year, month, 1, (7, 8)), MAIN,
                       f"AED {_fmt(SALARY)} has been credited to your account {{acct}} for Salary."))
    for _ in range(rng.randint(0, 1)):
        out.append(_atm(rng, _stamp(rng, year, month, rng.randint(2, days), (10, 22))))
    out += _transfer(rng, _stamp(rng, year, month, 2, (9, 12)), "local", MAIN, LANDLORD, RENT)
    out += _transfer(rng, _stamp(rng, year, month, rng.randint(3, 6), (18, 21)), "own", MAIN, "Alex Demo",
                     SAVING_TRANSFER)
    for _ in range(rng.randint(0, 2)):
        src = rng.choice([MAIN, SAVINGS])
        out += _transfer(rng, _stamp(rng, year, month, rng.randint(3, days), (10, 23)), "local", src,
                         rng.choice(FRIENDS), float(rng.choice([50, 70, 90, 120, 150, 200])))
    return out


def generate(months: int = 6, seed: int = 7, now: Optional[datetime] = None) -> list[RawMessage]:
    """Synthetic alert emails for the last `months` months, ending at `now` (default: current time)."""
    rng = random.Random(seed)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(tzinfo=None)
    local_now = now + UAE_OFFSET
    travel_month = rng.randint(1, max(months - 1, 1))
    events: list[tuple] = []
    for i in range(months):
        index = local_now.year * 12 + local_now.month - 1 - (months - 1 - i)
        year, month = divmod(index, 12)
        events += _month_events(rng, year, month + 1, i == travel_month)
    events = sorted((e for e in events if e[0] <= local_now), key=lambda e: e[0])
    return [RawMessage(id=f"demo-{n}", date=_iso(local), sender=sender, subject=subject, body=body)
            for n, (local, sender, subject, body) in enumerate(events, 1)]


DEMO_BUDGETS = {"housing": 8000, "dining": 1400, "bills": 1300, "coffee": 1000, "groceries": 750, "shopping": 800,
                "health": 700, "taxi": 300, "transport": 200, "subscriptions": 200}


def seed(store, months: int = 6, seed: int = 7) -> int:
    """Fill an empty ledger with the demo: synthetic emails plus a few budgets. Returns emails added."""
    n = store.add_messages(generate(months=months, seed=seed))
    for category, limit in DEMO_BUDGETS.items():
        if category in store.categories.by_key:
            store.set_budget(category, limit)
    store.rebuild()
    return n
