"""App preferences, kept in <data dir>/settings.json (separate from the ledger database).

Everything here is cosmetic or about where data comes from; nothing in it is needed to
rebuild the ledger. Unknown keys are dropped and invalid values fall back to defaults.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "theme": "system",       # system | light | dark
    "currency": "code",      # code ("AED 1,234") | after ("1,234 AED") | none ("1,234")
    "number": "auto",        # auto (from the browser's language) | en | de | fr  (1,234.56 · 1.234,56 · 1 234,56)
    "logos": False,          # fetch merchant logos for your real data (off: fetching reveals where you shop)
    "demo_logos": True,      # the same, inside the demo area (synthetic data, so on by default)
    "mode": "real",          # real | demo  — which ledger the dashboard shows
    "banks": [],             # bank profile names picked during setup; empty means "all"
    "onboarded": False,      # the welcome flow was finished or skipped
}

CHOICES = {
    "theme": {"system", "light", "dark"},
    "currency": {"code", "after", "none"},
    "number": {"auto", "en", "de", "fr"},
    "mode": {"real", "demo"},
}


def path(data_dir: Path) -> Path:
    return data_dir / "settings.json"


def _clean(key: str, value: Any) -> Any:
    default = DEFAULTS[key]
    if key in CHOICES:
        return value if value in CHOICES[key] else default
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, list):
        return [str(v) for v in value][:50] if isinstance(value, list) else default
    return value


def load(data_dir: Path) -> dict:
    out = dict(DEFAULTS)
    try:
        saved = json.loads(path(data_dir).read_text())
    except (OSError, ValueError):
        saved = {}
    if isinstance(saved, dict):
        out.update({k: _clean(k, v) for k, v in saved.items() if k in DEFAULTS})
    return out


def save(data_dir: Path, changes: dict) -> dict:
    """Merge `changes` into the stored settings (atomically) and return the result."""
    unknown = set(changes) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown setting: {', '.join(sorted(unknown))}")
    for k, v in changes.items():
        if k in CHOICES and v not in CHOICES[k]:
            raise ValueError(f"{k} must be one of {sorted(CHOICES[k])}")
    current = load(data_dir)
    current.update({k: _clean(k, v) for k, v in changes.items()})
    data_dir.mkdir(parents=True, exist_ok=True)
    tmp = path(data_dir).with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2) + "\n")
    os.replace(tmp, path(data_dir))
    return current
