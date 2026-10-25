"""Fetch bank and pay-later emails from Gmail into a ledger. Shared by the CLI and the app."""
from pathlib import Path
from typing import Optional

from .sources import Gmail
from .store import Store


def run_sync(st: Store, data: Path, full: bool = False, limit: int = 2000, only: Optional[list[str]] = None,
             progress=lambda **kw: None) -> dict:
    """Fetch new bank emails from Gmail into `st` — the same steps as `inbox_ledger sync`.

    The first run opens Google's consent page in your browser (read-only access)."""
    d = data
    if not (d / "token.json").is_file():
        progress(step="authorizing", message="Waiting for you to allow read-only access in your browser…")
    gmail = Gmail(d / "credentials.json", d / "token.json")
    after = None if full else st.latest_message_date()
    fetched, total = {}, 0
    for bank in [*st.banks, *st.providers]:
        if not bank.gmail_query or (only and bank in st.banks and bank.name not in only):
            continue
        progress(step="fetching", message=f"Reading {bank.name} emails…", bank=bank.name)
        msgs = list(gmail.fetch(bank.gmail_query, after=after, limit=limit))
        fetched[bank.name] = len(msgs)
        total += st.add_messages(msgs)
    progress(step="organizing", message="Organizing transactions…")
    return {"fetched": fetched, "added": total, **st.rebuild()}
