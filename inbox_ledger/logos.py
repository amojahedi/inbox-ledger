"""Merchant brands and their logos.

Brands (defaults/brands.yaml, plus an optional <data dir>/brands.yaml) map merchant
names to a brand colour and the brand's own website. When the user turns logos on,
`fetch_icon` downloads the icon straight from that website — the apple-touch-icon or
favicon its own pages declare — never through a third-party icon service. Results are
cached on disk, including failures, so each brand is fetched at most once.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import struct
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import yaml

TIMEOUT = 4.0               # seconds per request
BUDGET = 10.0               # seconds per brand, all attempts together
MAX_PAGE = 512 * 1024       # bytes of homepage HTML we are willing to read
MAX_ICON = 400 * 1024       # bytes per icon
MIN_PIXELS = 32
MISS_TTL = 7 * 24 * 3600    # retry a brand without a usable icon after a week
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
              "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")
MEDIA = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
         "ico": "image/x-icon", "svg": "image/svg+xml"}


@dataclass
class Brand:
    key: str
    name: str
    domain: str
    color: str = ""
    match: list[str] = field(default_factory=list)
    icon: str = ""

    def public(self) -> dict:
        return {"key": self.key, "name": self.name, "color": self.color}


class Brands:
    def __init__(self, brands: list[Brand]):
        self.items = brands
        self.by_key = {b.key: b for b in brands}
        self._exact: dict[str, Brand] = {}
        words: dict[str, Brand] = {}
        for b in brands:
            for m in b.match or [b.name]:
                m = m.strip().lower()
                if m.startswith("="):
                    self._exact[m[1:].strip()] = b
                elif m:
                    words.setdefault(m, b)
        self._words = words
        alts = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
        self._rx = re.compile(rf"(?<![a-z0-9])(?:{alts})(?![a-z0-9])") if alts else None

    @classmethod
    def load(cls, *paths: Optional[Path]) -> "Brands":
        merged: dict[str, Brand] = {}
        for p in paths:
            if p and p.is_file():
                for d in (yaml.safe_load(p.read_text()) or {}).get("brands", []):
                    b = Brand(key=str(d["key"]), name=str(d.get("name", d["key"])), domain=str(d["domain"]),
                              color=str(d.get("color", "")), match=[str(m) for m in d.get("match", [])],
                              icon=str(d.get("icon", "")))
                    merged[b.key] = b
        return cls(list(merged.values()))

    def find(self, merchant: str) -> Optional[Brand]:
        """The brand for a merchant key or display name, if any (longest keyword wins)."""
        name = re.sub(r"\s+", " ", (merchant or "").lower()).strip()
        if not name:
            return None
        if name in self._exact:
            return self._exact[name]
        if name in self.by_key:
            return self.by_key[name]
        if self._rx:
            hits = self._rx.findall(name)
            if hits:
                return self._words[max(hits, key=len)]
        return None


# ---- fetching ---------------------------------------------------------------

class _IconLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[int, str]] = []  # (score, href)

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        rel, href = a.get("rel", "").lower().split(), a.get("href", "").strip()
        if not href or not ({"icon", "apple-touch-icon", "apple-touch-icon-precomposed"} & set(rel)):
            return
        sizes = [int(n) for n in re.findall(r"(\d+)x\d+", a.get("sizes", ""))]
        size = max(sizes) if sizes else 0
        score = size
        if "apple-touch-icon" in rel or "apple-touch-icon-precomposed" in rel:
            score += 1000 + (180 if not size else 0)
        elif href.lower().endswith(".svg") or "svg" in a.get("type", ""):
            score += 400  # scales cleanly, but brand marks in SVG are often monochrome
        self.links.append((score, href))


def _check_public(url: str) -> None:
    """Only https URLs on named hosts that resolve to public addresses: a brand page must not be able
    to point the fetcher at this machine or the local network (directly or through a redirect)."""
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme != "https" or not host or re.fullmatch(r"[\d.:\[\]]+", host):
        raise ValueError("only https URLs on named hosts")
    for info in socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP):
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValueError(f"{host} resolves to a non-public address")


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_PublicRedirects)


def _get(url: str, limit: int, timeout: float = TIMEOUT) -> tuple[bytes, str]:
    _check_public(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with _opener.open(req, timeout=max(0.5, timeout)) as res:  # each redirect hop is checked too
        if urlparse(res.geturl()).scheme != "https":
            raise ValueError("redirected away from https")
        data = res.read(limit + 1)
        if len(data) > limit:
            raise ValueError("too large")
        return data, res.geturl()


def sniff(data: bytes) -> Optional[str]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] == b"\x00\x00\x01\x00":
        return "ico"
    head = data[:512].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:2048].lower()):
        return "svg"
    return None


def _pixels(data: bytes, kind: str) -> int:
    """Rough icon size, so a 16px favicon loses to a 180px touch icon."""
    try:
        if kind == "png":
            return min(struct.unpack(">II", data[16:24]))
        if kind == "ico":
            n = struct.unpack("<H", data[4:6])[0]
            return max((data[6 + 16 * i] or 256) for i in range(min(n, 16)))
    except (struct.error, IndexError):
        return 0
    return 128  # jpg / gif / webp / svg: assume usable


def candidates(brand: Brand, deadline: float = 0) -> list[str]:
    """Icon URLs to try, best first: an explicit icon, the homepage's own <link> icons, well-known paths."""
    root = f"https://{brand.domain}/"
    urls: list[str] = []
    if brand.icon:
        urls.append(urljoin(root, brand.icon))
    try:
        html, final = _get(root, MAX_PAGE, min(TIMEOUT, (deadline or time.time() + TIMEOUT) - time.time()))
        parser = _IconLinks()
        parser.feed(html.decode("utf-8", "replace"))
        urls += [urljoin(final, href) for _, href in sorted(parser.links, key=lambda x: -x[0])]
        root = urljoin(final, "/")
    except Exception:
        pass
    # Well-known paths, sharpest first — many sites render their <head> with JavaScript.
    urls += [urljoin(root, p) for p in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png",
                                        "/android-chrome-192x192.png", "/favicon-196x196.png", "/logo192.png",
                                        "/favicon-32x32.png", "/favicon.ico")]
    seen: set[str] = set()
    return [u for u in urls if not (u in seen or seen.add(u)) and not u.startswith("data:")]


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def cached(brand: Brand, cache: Path) -> Optional[Path]:
    for ext in MEDIA:
        p = cache / f"{brand.key}.{ext}"
        if p.is_file():
            return p
    return None


def fetch_icon(brand: Brand, cache: Path) -> Optional[Path]:
    """Return the cached icon for `brand`, downloading it once if needed. None means no icon."""
    hit = cached(brand, cache)
    if hit:
        return hit
    miss = cache / f"{brand.key}.miss"
    if miss.is_file() and time.time() - miss.stat().st_mtime < MISS_TTL:
        return None
    with _locks_guard:
        lock = _locks.setdefault(brand.key, threading.Lock())
    with lock:
        hit = cached(brand, cache)
        if hit:
            return hit
        best: Optional[tuple[int, bytes, str]] = None
        deadline = time.time() + BUDGET
        for url in candidates(brand, deadline):
            left = deadline - time.time()
            if left <= 0:
                break
            try:
                data = _get(url, MAX_ICON, min(TIMEOUT, left))[0]
            except Exception:
                continue
            kind = sniff(data)
            if not kind:
                continue
            px = _pixels(data, kind)
            if not best or px > best[0]:
                best = (px, data, kind)
            if px >= 96:
                break
        cache.mkdir(parents=True, exist_ok=True)
        if not best or best[0] < MIN_PIXELS:  # a blurry 16px favicon looks worse than the monogram
            miss.write_text(time.strftime("%Y-%m-%dT%H:%M:%S\n"))
            return None
        out = cache / f"{brand.key}.{best[2]}"
        out.write_bytes(best[1])
        miss.unlink(missing_ok=True)
        return out
