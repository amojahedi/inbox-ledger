"""Where raw emails come from: the Gmail API, a Google Takeout .mbox, or JSONL."""
from __future__ import annotations

import base64
import json
import mailbox
import re
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Iterator, Optional

from .parsing import RawMessage

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", html)
    html = re.sub(r"(?i)<li[^>]*>", " * ", html)
    return unescape(re.sub(r"<[^>]+>", " ", html))


def read_jsonl(path: Path) -> Iterator[RawMessage]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            yield RawMessage(id=d["id"], date=d["date"], sender=d["sender"],
                             subject=d.get("subject", ""), body=d["body"])


def read_mbox(path: Path) -> Iterator[RawMessage]:
    for msg in mailbox.mbox(str(path)):
        body = ""
        parts = msg.walk() if msg.is_multipart() else [msg]
        for part in parts:
            ctype = part.get_content_type()
            if ctype in ("text/plain", "text/html"):
                payload = part.get_payload(decode=True) or b""
                text = payload.decode(part.get_content_charset() or "utf-8", "replace")
                body = text if ctype == "text/plain" else (body or html_to_text(text))
                if ctype == "text/plain":
                    break
        sender = re.sub(r".*<|>.*", "", str(msg.get("From", "")))
        yield RawMessage(
            id=str(msg.get("Message-ID", "")).strip("<>") or str(hash(body)),
            date=parsedate_to_datetime(msg["Date"]).isoformat(),
            sender=sender,
            subject=str(make_header(decode_header(msg.get("Subject", "")))),
            body=body,
        )


class Gmail:
    """Read-only Gmail access through your own Google Cloud OAuth client."""

    def __init__(self, credentials_file: Path, token_file: Path):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        if token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not credentials_file.exists():
                    raise FileNotFoundError(
                        f"{credentials_file} not found — see README › Connect Gmail")
                creds = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_file), SCOPES).run_local_server(port=0)
            token_file.write_text(creds.to_json())
        self.api = build("gmail", "v1", credentials=creds, cache_discovery=False)

    def fetch(self, query: str, after: Optional[str] = None, limit: int = 2000) -> Iterator[RawMessage]:
        if after:
            query += f" after:{after[:10].replace('-', '/')}"
        req = self.api.users().messages().list(userId="me", q=query, maxResults=100)
        seen = 0
        while req is not None and seen < limit:
            res = req.execute()
            for ref in res.get("messages", []):
                yield self._get(ref["id"])
                seen += 1
            req = self.api.users().messages().list_next(req, res)

    def _get(self, msg_id: str) -> RawMessage:
        m = self.api.users().messages().get(userId="me", id=msg_id, format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in m["payload"].get("headers", [])}
        plain, html = [], []

        def walk(part):
            data = part.get("body", {}).get("data")
            if data:
                text = base64.urlsafe_b64decode(data).decode("utf-8", "replace")
                (plain if part.get("mimeType") == "text/plain" else html).append(text)
            for p in part.get("parts", []):
                walk(p)

        walk(m["payload"])
        body = "\n".join(plain) or html_to_text("\n".join(html))
        sender = re.sub(r".*<|>.*", "", headers.get("from", ""))
        from datetime import datetime, timezone
        date = datetime.fromtimestamp(int(m["internalDate"]) / 1000, timezone.utc).isoformat()
        return RawMessage(id=m["id"], date=date, sender=sender,
                          subject=headers.get("subject", ""), body=body)
