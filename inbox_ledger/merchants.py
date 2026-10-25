"""Merchant name normalization.

Card networks append location noise to merchant names ("NOON FOOD DUBAI GB",
"Hala Taxi Ras Al Khaimah AE"). We strip it so one merchant gets one key, which is
what user corrections attach to.
"""
import re

_CITIES = [
    "abu dhabi", "dubai", "sharjah", "ajman", "al ain", "ras al khaimah", "fujairah",
    "umm al quwain", "london", "dublin", "luxembourg", "amsterdam", "san francisco",
    "seattle", "singapore", "berlin", "paris", "new york", "mumbai", "riyadh", "doha", "abudhabi",
]
_COUNTRY = re.compile(r"\s+(?:[A-Z]{2}|ARE|UAE|USA|GBR)$")
_CITY = re.compile(r"\s+(?:" + "|".join(re.escape(c) for c in _CITIES) + r")$", re.I)
_NOISE = re.compile(r"[*#]+|\s\+?\d{7,}|\bpending\b|,?\s+\d+$|,\s*$", re.I)
_SUFFIX = re.compile(r"(?:\s+(?:fz|llc|l\.l\.c|fze|fzco|fzc|co|inc|ltd|trading))+\.?$", re.I)


def _strip(name: str) -> str:
    original = re.sub(r"\s+", " ", name).strip(" .,-")
    # Order matters: "Hala Taxi Ras Al Khaimah AE" -> drop country, then one city.
    name = _COUNTRY.sub("", original)
    name = _CITY.sub("", name)
    name = _NOISE.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .,-")
    name = _SUFFIX.sub("", name).strip(" .,-")
    return name or original


def merchant_key(raw: str) -> str:
    return _strip(raw).lower()


def display_name(raw: str) -> str:
    name = _strip(raw)
    if name.isupper() or name.islower():
        name = " ".join(w if any(c in w for c in "&/") else w.capitalize() for w in name.split())
    return name
