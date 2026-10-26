# What the numbers mean

Every screen in Ledger uses the same nine words, and every one of them is worked out in one place
(`inbox_ledger/store.py`) and served once (`GET /api/summary`, `GET /api/trends`,
`GET /api/category/{key}`). The short version of each word, the sentence the app shows beside a
number, lives in `inbox_ledger/defaults/definitions.yaml` and is served by `GET /api/definitions`.
This page is the longer version: what counts, what does not, and how the arithmetic adds up.

All the examples use the example data (`python -m inbox_ledger demo`): salary AED 30,000, rent
AED 8,000, AED 8,000 moved to savings, and spending that is never above AED 14,000 a month.

## The words

**Came in** — money that arrived in your accounts, like your salary. Refunds and money a friend
paid back are not income, so they are left out. In the API this is `received`.

**Spent** — card purchases, debits and money you sent to people, with refunds taken off. Moves to
your own savings, settled transfers and anything you marked as didn’t happen are not counted. In
the API this is `spent`.

**Saved** — money you moved to your own savings this month. If some came back, it is taken off, so
this is what actually stayed put. In the API this is `moved`. (See *Which way a move went* below.)

**Left** — what is still there after spending and saving: Came in − Spent − Saved. In the API
this is `left`.

**Fixed** — the part of your spending that is much the same every month: the categories flagged
`fixed: true` in `categories.yaml` (Housing, Bills & Utilities and Subscriptions by default; your own
categories are everyday unless you say otherwise). In the API this is `fixed`.

**Everyday** — everything else you spent: Spent − Fixed. In the API this is `everyday`.

**Settled** — money you sent someone and got back from them within 45 days. It cancels out, so it
is left out of every total. Settled rows are listed under the “Settled” chip in Activity.

**Hidden** — a transaction you marked as didn’t happen. It stays in the list for reference but is
left out of every total.

**Needs review** — purchases Ledger could not place in a category. They count as spending under
“Other” until you pick a category; in the API this is `uncategorized`.

## What adds up to what

These hold for every month, and `tests/test_numbers.py` checks them on a freshly generated
example ledger:

- Spent = the sum of every category = the sum of every day = the sum of every hour = the month’s
  bar on Trends = the category lines on Trends added together.
- Came in − Spent − Saved = Left.
- Fixed + Everyday = Spent.
- A category’s total on its own page = its share of the month = its places added together.
- Percentages are whole numbers that add up to exactly 100 (largest remainder, never per-row
  rounding).
- Marking one transaction as didn’t happen moves every one of those totals by exactly its amount.

Example, October: 30,000 came in, 13,900.00 spent (8,000 of it fixed, 5,900 everyday),
8,000 saved, 8,100 left.

## Which way a move went

A move between your own accounts is “Saved” when it leaves your main account (the one your income
lands in) and “came back” when it leaves any other account of yours, or arrives in the main one.
Came back is taken off, so Saved is the net figure: move 8,000 out and 2,000 back, and Saved is
6,000, not 10,000.

Limitation: this needs the alert to name the account the money left. When it does not, or when no
income has arrived yet so there is no main account to compare with, every own-account move counts
as Saved. The example data always names the account.

## Time

The server decides what day it is, not the browser. `elapsed_days` is the full month for a month
that is over and for example data; for the month in progress it is today’s day of the month.
`in_progress` is true only for the current month of real data. `previous_spent_to_date` is last
month’s spending over the same number of days, and is only filled in while the month is in
progress, so “up 5% on September” always compares like with like. For demos and tests, the
environment variable `LEDGER_TODAY=YYYY-MM-DD` sets the date.

## Rounding

- Single transactions and the month’s headline keep their cents (AED 13,900.00).
- Totals on cards, tiles and charts are whole units.
- Percentages come from the largest-remainder helper (`percents()` in the app, `share` fields in
  the API) and always add up to 100.
- Foreign-currency purchases are converted once, at the rate in `categories.yaml`, when the
  ledger is rebuilt, and every total uses that converted figure.
