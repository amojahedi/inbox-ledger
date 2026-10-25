<p align="center">
  <img src="inbox_ledger/web/icon.svg" width="64" height="64" alt="">
</p>

<h1 align="center">Ledger</h1>

<p align="center">
  Your bank already emails you every transaction.<br>
  Ledger turns those emails into a private, beautiful monthly budget — on your own machine.
</p>

<p align="center">
  <img src="docs/screenshots/overview-light.png" width="860" alt="Ledger overview: monthly total, category breakdown, daily spending, six-month trend, budgets and top merchants">
</p>

---

## Why

Most budgeting apps want your bank password, or a paid aggregator that doesn't support your bank. But your bank already sends an email for every card payment and transfer. Ledger reads those alerts (read-only), understands them, and gives you a clear picture of where your money goes. No third party in between, and no data leaving your laptop.

## What it does

- **Reads your bank alerts from Gmail.** Read-only OAuth, with only the bank's sender addresses queried. You can also import a Google Takeout `.mbox`.
- **Understands them.** Each bank is a small YAML file of patterns. Card purchases, account debits, transfers and credits become structured transactions. Mashreq (UAE) is built in, and adding your bank takes no code.
- **Removes double counting.** Banks often send two emails for one movement (a transfer receipt and a debit alert). Ledger pairs them and keeps one.
- **Knows what isn't spending.** Moving money between your own accounts is tracked separately and never inflates your monthly total.
- **Learns from one correction.** Tell it once that *Golden Sands* is Shopping, or that a transfer to someone is between your own accounts. That merchant is handled the same way, past and future, from then on. Every learned rule is listed and can be undone. A rule can also be tied to one exact amount, for when one app covers different things (your AED 32.50 coffee order on a food-delivery app, say).
- **Understands pay-later.** A card charge that just says "Tabby" is paired with Tabby's own email (same amount, seconds apart) and shown as the real store, e.g. "Noon · via Tabby". Charges covering several orders are split. A Pay later card shows this month's instalments and what you still owe per order. Providers are YAML profiles too, so Tamara or Postpay can be added the same way.
- **Your categories, not just ours.** Create a category from any transaction in two taps (name and colour), then budget and teach rules with it like a built-in one.
- **Shows you the month.** Totals against last month, what came in and what you saved, a category breakdown, daily and hourly spending, a six-month trend, budgets per category, and top merchants. Light and dark mode, desktop and phone.

<p align="center">
  <img src="docs/screenshots/activity.png" width="49%" alt="Activity list grouped by day">
  <img src="docs/screenshots/rules.png" width="49%" alt="Rules Ledger has learned">
</p>
<p align="center">
  <img src="docs/screenshots/mobile.png" width="24%" alt="Overview on a phone">
  <img src="docs/screenshots/mobile-dark.png" width="24%" alt="Activity in dark mode on a phone">
  <img src="docs/screenshots/overview-dark.png" width="49%" alt="Overview in dark mode">
</p>

## Try it in one minute (demo data)

```bash
git clone https://github.com/amojahedi/inbox-ledger && cd inbox-ledger
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
INBOX_LEDGER_DATA=demo-data python -m inbox_ledger demo
INBOX_LEDGER_DATA=demo-data python -m inbox_ledger serve
```

Open http://127.0.0.1:8765. Everything in the demo is synthetic, and the dashboard labels it as example data.

## Use it with your own email

1. **Create a Google OAuth client.** This is free and takes about 3 minutes.
   In [Google Cloud Console](https://console.cloud.google.com/): create a project, enable the **Gmail API**, configure the OAuth consent screen (External, add yourself as a test user), then go to *Credentials → Create credentials → OAuth client ID → Desktop app*. Download the JSON and save it as `data/credentials.json`.
2. **Sync**, which opens a browser once to grant read-only access:
   ```bash
   python -m inbox_ledger sync
   ```
3. **Open the dashboard:**
   ```bash
   python -m inbox_ledger serve
   ```

Run `sync` again whenever you like. It only fetches emails newer than the last one it saw.

Prefer not to connect Gmail? Export your mail with [Google Takeout](https://takeout.google.com) and run `python -m inbox_ledger import path/to/mail.mbox`.

## Supported banks

| Bank | Country | Status |
|---|---|---|
| Mashreq | UAE | verified |
| Emirates NBD | UAE | beta |
| Liv. (Emirates NBD) | UAE | beta |
| Abu Dhabi Islamic Bank (ADIB) | UAE | beta |
| Dubai Islamic Bank (DIB) | UAE | beta |
| Emirates Islamic | UAE | beta |
| ADCB | UAE | beta |
| First Abu Dhabi Bank (FAB) | UAE | beta |
| RAKBANK | UAE | beta |
| Commercial Bank of Dubai (CBD) | UAE | beta |
| Wio | UAE | beta |
| Any other bank | anywhere | fallback |

**verified** means the patterns were checked against real alerts. **beta** profiles were written from publicly posted example alerts and have not been verified against real mail yet, so expect gaps; the *Any bank* fallback may still catch what they miss. **fallback** is a generic profile for common English phrasings ("purchase of AED 12.34 at ...", "debited from your account ...", "credited with ...") from alert-style senders (`alerts@`, `notifications@`, `noreply@`) at bank domains. Bank-specific profiles always win, and anything the fallback reads is tagged with a `generic_` pattern name so it can be flagged as less certain.

If your bank is a beta profile and an alert is missed, or your bank is not listed, please send a sample (see below).

## Add your bank

**Easiest: contribute a redacted sample.** Open an issue or pull request with the alert email body (and its subject and sender address) for each kind of alert you get: card purchase, debit, credit, transfer. Replace names, account and card numbers and balances with made-up values, but keep the wording and layout exactly as it arrived. With a sample, a profile takes minutes; without one it is guesswork.

**Or write the profile yourself.** Copy [`inbox_ledger/defaults/banks/mashreq.yaml`](inbox_ledger/defaults/banks/mashreq.yaml) to `data/banks/yourbank.yaml` and edit it. The file covers:

- `gmail_query`: which emails to fetch
- `senders`: which sender addresses this profile handles
- `patterns`: one regex per email type, with named groups `amount`, `currency`, `last4`, `merchant`, `counterparty`, `when`, `transfer_type`, `status`. Optional per pattern: `label` (merchant name when the alert names none), `subject_regex` (extra groups taken from the subject line) and `when_format` (common date formats are tried automatically)
- `dedupe`: which alert mirrors which receipt
- `status`: `verified` once you have checked it against real alerts, otherwise `beta`

Your files override built-in ones with the same file name, and profiles you add are always tried before the *Any bank* fallback.

Pay-later providers live in [`defaults/paylater/`](inbox_ledger/defaults/paylater/) and follow the same idea: patterns for the provider's emails, plus `card_merchant`, the name the bank alert shows.

Then run `python -m inbox_ledger rebuild`. Raw emails are stored, so improving a pattern re-parses your whole history instantly. Pull requests with new bank profiles are very welcome.

Categories, keywords and FX rates live in [`categories.yaml`](inbox_ledger/defaults/categories.yaml). You can override them with `data/categories.yaml`.

## Privacy

- Gmail access is **read-only** (`gmail.readonly`), and only your bank's sender addresses are queried.
- Everything is stored in a local SQLite file in `data/`, which is git-ignored, as are `credentials.json` and `token.json`.
- The server binds to `127.0.0.1`. There is no telemetry and there are no external requests from the dashboard: no CDNs, fonts or analytics.

## How it works

```
Gmail / .mbox ──▶ raw_messages ──▶ bank YAML patterns ──▶ transactions
                                                      │
                     merchant normalization ◀─────────┤
                     mirror dedupe          ◀─────────┤
                     learned rules › keywords › kind  ◀┘
                                                      ▼
                                  FastAPI ──▶ dashboard (vanilla JS + SVG)
```

| Layer | Choice | Why |
|---|---|---|
| Parsing | Declarative YAML + regex | New banks without code; rebuildable from raw emails |
| Storage | SQLite | One file, zero setup, easy to back up |
| API | FastAPI | Typed, small, self-documenting at `/api/docs` |
| UI | Vanilla JS, hand-drawn SVG charts | No build step, no dependencies, fast |
| Design | System font (SF Pro), HIG-inspired | Feels native on Apple devices; colour-blind-safe palette in both themes |

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

## License

MIT
