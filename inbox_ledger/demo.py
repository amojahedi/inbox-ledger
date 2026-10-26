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
# What a full month's spending adds up to, rent included: the current month lands on it exactly,
# earlier months within about AED 120 of it, and no month ever passes AED 14,000.
MONTH_TOTAL = 13900.00
LANDLORD = "LANDLORD"
FRIENDS = ["SARA AHMED", "LAYLA HASSAN", "DANIEL ROSS", "PRIYA MENON", "YUSUF RAHMAN", "NOUR KHALIL"]
# Mirrors categories.yaml; foreign-currency charges are converted at this rate when the month is summed.
FX = {"AED": 1.0, "USD": 3.6725}

# Typical day-to-day spending per category (AED), rent and fixed charges aside. "shopping" includes the
# pay-in-4 instalments, "health" sits on top of the gym membership. Each month scales these a few percent
# either way so that it adds up to its total; a trip month scales them down to pay for the flight.
TARGETS = {"dining": 1000, "coffee": 550, "groceries": 600, "shopping": 950, "health": 150,
           "taxi": 350, "transport": 250, "entertainment": 250, "other": 70}

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
    ("OUNASS DUBAI AE", 2.5, (1, 1), (12, 22), "shopping"),
    ("6TH STREET DUBAI AE", 1.5, (1, 1), (12, 22), "shopping"),
    ("AMAZON.AE DUBAI AE", 1.0, (1, 2), (10, 23), "shopping"),
    ("NAMSHI DUBAI AE", 1.2, (0, 1), (10, 23), "shopping"),
    ("LIFE PHARMACY DUBAI AE", 0.6, (0, 1), _DAY, "health"),
    ("SEPHORA DUBAI AE", 1.2, (0, 1), (12, 21), "health"),
    ("F45 TRAINING DUBAI AE", 0.5, (1, 2), (6, 8), "health"),
    ("CAREEM RIDE DUBAI AE", 1.0, (4, 7), (7, 23), "taxi"),
    ("SALIK DUBAI AE", 1.0, (1, 1), _DAY, "transport"),
    ("ENOC DUBAI AE", 1.5, (1, 2), _DAY, "transport"),
    ("RTA NOL TOP UP DUBAI AE", 0.5, (1, 2), _DAY, "transport"),
    ("VOX CINEMAS DUBAI AE", 1.0, (1, 2), _EVENING, "entertainment"),
    ("PLATINUMLIST TICKETS DUBAI AE", 2.0, (0, 1), _EVENING, "entertainment"),
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
    ("DU DUBAI AE", 349.00, 21, 11, "AED"),
    ("ETISALAT DUBAI AE", 349.00, 18, 10, "AED"),
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


def _atm(rng: random.Random, local: datetime, amount: float) -> tuple:
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


def _instalments(total: float, n: int = 4) -> list[tuple[int, float]]:
    """Pay-in-4 schedule: (days after the order, amount) per instalment, the last one taking the rounding."""
    parts = [round(total / n, 2)] * (n - 1)
    parts.append(round(total - sum(parts), 2))
    return [(30 * i, part) for i, part in enumerate(parts)]


def _tabby_order(rng: random.Random, local: datetime, store: str, total: float, n: int = 4) -> list[tuple]:
    """A pay-in-4 order: each instalment is a 'Tabby' card charge plus Tabby's email naming the store."""
    order = f"NA{rng.randint(10**11, 10**12 - 1)}{rng.randint(1000, 9999)}"
    parts = [amount for _, amount in _instalments(total, n)]
    dates = [local + timedelta(days=offset) for offset, _ in _instalments(total, n)]
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


def _month_events(rng: random.Random, year: int, month: int, travel: bool, total: float, paylater: float,
                  upto: Optional[int] = None) -> list[tuple]:
    """One month of email whose spending adds up to exactly `total` (rent included). `paylater` is what
    this month's pay-in-4 instalments already cost; `upto` squeezes day-to-day spending into the days so
    far (the current month), so the month to date already reads like a full month instead of stopping short."""
    days = calendar.monthrange(year, month)[1]
    span = min(days, upto or days)
    out: list[tuple] = []
    fixed = RENT + paylater  # spending settled before the day-to-day purchases are drawn

    for merchant, amount, day, hour, currency in _RECURRING:
        if amount is None:
            amount = round(rng.uniform(270, 330), 2)
        out.append(_card(rng, _stamp(rng, year, month, day, (hour, hour)), merchant, amount, currency))
        fixed += round(amount * FX[currency], 2)

    if travel:  # the flight, plus some cash for the trip
        flight, cash = round(rng.uniform(800, 1100), 2), 200.0
        out.append(_card(rng, _stamp(rng, year, month, rng.randint(2, min(span, 20)), (10, 22)), "EMIRATES DUBAI AE",
                         flight, "AED"))
        out.append(_atm(rng, _stamp(rng, year, month, rng.randint(2, max(2, span)), (10, 22)), cash))
        fixed += flight + cash

    for _ in range(rng.randint(0, 1)):  # the odd small transfer to a friend
        amount = float(rng.choice([50, 70, 90, 120]))
        out += _transfer(rng, _stamp(rng, year, month, rng.randint(3, max(3, span)), (10, 23)), "local",
                         rng.choice([MAIN, SAVINGS]), rng.choice(FRIENDS), amount)
        fixed += amount

    out.append(_advice(_stamp(rng, year, month, 1, (7, 8)), MAIN,
                       f"AED {_fmt(SALARY)} has been credited to your account {{acct}} for Salary."))
    out += _transfer(rng, _stamp(rng, year, month, 2, (9, 12)), "local", MAIN, LANDLORD, RENT)
    out += _transfer(rng, _stamp(rng, year, month, rng.randint(3, 6), (18, 21)), "own", MAIN, "Alex Demo",
                     SAVING_TRANSFER)

    # Day-to-day purchases: draw them, then scale each category toward its share of what is left.
    drawn: dict[str, list] = {}
    for merchant, size, (cmin, cmax), hours, group in _CARD_MERCHANTS:
        for _ in range(rng.randint(cmin, cmax)):
            drawn.setdefault(group, []).append((merchant, size * rng.uniform(0.7, 1.3), hours))
    targets = {group: (max(TARGETS[group] - paylater, 100) if group == "shopping" else TARGETS[group])
               * rng.uniform(0.96, 1.04) for group in drawn}
    k = (total - fixed) / sum(targets.values())
    purchases: list[list] = []
    for group, items in drawn.items():
        per = targets[group] * k / sum(weight for _, weight, _ in items)
        purchases += [[merchant, round(weight * per, 2), hours] for merchant, weight, hours in items]
    # Rounding leaves a few fils either way; the biggest purchase takes them so the month adds up to the cent.
    biggest = max(purchases, key=lambda p: p[1])
    biggest[1] = round(biggest[1] + (total - fixed) - sum(p[1] for p in purchases), 2)
    for merchant, amount, hours in purchases:
        out.append(_card(rng, _stamp(rng, year, month, rng.randint(1, span), hours), merchant, amount, "AED"))
    return out


def generate(months: int = 6, seed: int = 7, now: Optional[datetime] = None) -> list[RawMessage]:
    """Synthetic alert emails for the last `months` months, ending at `now` (default: current time)."""
    rng = random.Random(seed)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(tzinfo=None)
    local_now = now + UAE_OFFSET
    travel_month = rng.randint(1, max(months - 2, 1))  # never the current month, so it reads like a typical one
    plan = []
    for i in range(months):
        index = local_now.year * 12 + local_now.month - 1 - (months - 1 - i)
        year, month = divmod(index, 12)
        current = i == months - 1
        plan.append((year, month + 1, i == travel_month, local_now.day - 1 if current else None))

    # One small pay-in-4 order a month, so the Pay later card always has something to show. Its instalments
    # are settled first: each month then absorbs the ones already charged to it.
    events: list[tuple] = []
    charged: dict[tuple[int, int], float] = {}
    for year, month, _, upto in plan:
        span = min(calendar.monthrange(year, month)[1], upto or 31)
        store, lo, hi = rng.choice(_TABBY_STORES)
        when, order_total = _stamp(rng, year, month, rng.randint(3, max(3, min(span, 22))), (11, 21)), round(rng.uniform(lo, hi), 2)
        events += _tabby_order(rng, when, store, order_total)
        for offset, amount in _instalments(order_total):
            due = when + timedelta(days=offset)
            if due <= local_now:
                charged[(due.year, due.month)] = round(charged.get((due.year, due.month), 0) + amount, 2)

    for year, month, travel, upto in plan:
        total = MONTH_TOTAL if upto else round(MONTH_TOTAL + rng.uniform(-120, 80), 2)
        events += _month_events(rng, year, month, travel, total, charged.get((year, month), 0.0), upto)
    events = sorted((e for e in events if e[0] <= local_now), key=lambda e: e[0])
    return [RawMessage(id=f"demo-{n}", date=_iso(local), sender=sender, subject=subject, body=body)
            for n, (local, sender, subject, body) in enumerate(events, 1)]


# Each budget sits just above the category's typical month, so the budget bars read as nearly used up.
DEMO_BUDGETS = {"housing": 8000, "dining": 1150, "bills": 1050, "shopping": 1100, "groceries": 700, "coffee": 650,
                "health": 550, "taxi": 400, "transport": 300, "entertainment": 300, "subscriptions": 200}


def seed(store, months: int = 6, seed: int = 7) -> int:
    """Fill an empty ledger with the demo: synthetic emails, a few budgets and a short wishlist.
    Returns emails added."""
    from datetime import date

    from . import wishlist
    n = store.add_messages(generate(months=months, seed=seed))
    for category, limit in DEMO_BUDGETS.items():
        if category in store.categories.by_key:
            store.set_budget(category, limit)
    store.rebuild()
    if not wishlist.wishes(store.db) and not wishlist.wishes(store.db, bought=True):
        today = date.today()
        y, m = divmod(today.year * 12 + today.month + 1, 12)  # the 1st, two months from now
        wishlist.add(store.db, {"name": "AirPods Pro", "price": 999, "link": "https://www.apple.com/ae/airpods-pro/",
                                "note": "For the gym and the metro"})
        wishlist.add(store.db, {"name": "A weekend in Georgia", "price": 4500, "note": "Flights and three nights in Tbilisi"})
        wishlist.add(store.db, {"name": "MacBook Air", "price": 5299, "link": "https://www.apple.com/ae/macbook-air/",
                                "note": "Before my birthday", "target": date(y, m + 1, 1).isoformat()})
        wishlist.save_settings(store.db, {"saved": 1200})
    return n
