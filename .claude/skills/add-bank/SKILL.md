---
name: add-bank
description: Add support for a new bank's alert emails to Ledger by writing a YAML profile (data/banks/<bank>.yaml, or a pull request to inbox_ledger/defaults/banks with tests) from a few redacted sample emails, then verify nothing is left unparsed. Use when the user says their bank is not supported, shows unparsed emails, or wants to add a bank. Needs no API key.
---

# Add a bank to Ledger (no API key needed)

Ledger understands a bank through one YAML file of regexes. You write it, check it against the user's real emails, and iterate until nothing is unparsed. Read `inbox_ledger/defaults/banks/mashreq.yaml` first: it is the schema and the style to copy. `inbox_ledger/parsing.py` (`load_bank`, `parse_message`) is how it is applied.

## 1. Get samples (privacy first)

- Ask for 2 to 3 alert emails per type (card purchase, account debit, credit, transfer), pasted into the chat, or find them locally with `python -m inbox_ledger rebuild` then querying `data/ledger.db` (`raw_messages`). Never read or print more mail than needed, and never touch files outside this repo.
- Ask the user to redact names, full account/card numbers and anything private. Amounts, merchants, dates and the last four digits of the account can stay: the patterns need them.
- Also note the sender address (it goes in `senders`) and the bank's time zone.

## 2. Write the profile

Create `data/banks/<bank>.yaml` (the user's private overrides; `data/` is git-ignored). If the user wants to contribute it, write `inbox_ledger/defaults/banks/<bank>.yaml` instead, using only redacted, synthetic text.

- Top-level keys: `name`, `gmail_query`, `senders` (regexes on the lowercased sender address, e.g. `'bank\.com$'`), `timezone` (IANA), `patterns`, and `dedupe` only if the bank sends two emails for one movement.
- Each pattern: `name`, `kind` (`card_purchase` | `account_debit` | `account_credit` | `transfer`), `direction` (`out` | `in` | `internal`), `regex`, and `when_format` (strptime) when the email states a date and time.
- Named groups: `amount` (required, digits only like `[\d,]*\.\d{2}`), `currency`, `last4`, `merchant`, `counterparty`, `when`, `transfer_type`, `status`.
- Regexes run with `re.S` on the body after all whitespace is collapsed to single spaces; the first matching pattern wins, so put specific patterns first. Match the wording around the values, not the values themselves, and keep them tolerant (`.+?` for merchants, optional parts as `(?: ...)?`).
- Refunds and credits need their own pattern with `direction: in`. Failed or declined alerts must not match (use `failed_statuses` for transfers).

## 3. Verify

1. Check each sample against the profile:
   ```bash
   python - <<'PY'
   from pathlib import Path
   from inbox_ledger.parsing import RawMessage, load_bank, parse_message
   bank = load_bank(Path("data/banks/<bank>.yaml"))
   sample = RawMessage("1", "2026-01-01T00:00:00Z", "alerts@<bank>.com", "subject", "<paste the body>")
   print(parse_message(sample, [bank]))
   PY
   ```
   Check amount, currency, last4, merchant, direction and the local time on every sample.
2. Run `python -m inbox_ledger rebuild` and read the output: `unparsed` should be 0 for the bank's real alerts (OTPs, statements and marketing legitimately stay unparsed). If emails remain, look at a few, extend the patterns, rebuild again.
3. Run `python -m pytest -q`: it must still pass.

## 4. If contributing to the repo

Add `tests/test_<bank>.py` with synthetic emails (copy the style of `tests/helpers.py` and `tests/test_parsing.py`) covering each pattern, a refund or failed case, and the time zone. Never commit real emails, names or numbers. Mention the bank, its country and sender addresses in the pull request.

Want Claude to do this from the command line instead, with your own API key? See "Bring your own Claude (optional)" in the README (`ai-profile`).
