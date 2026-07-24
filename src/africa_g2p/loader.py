"""Loading and caching of per-language rule files and the language registry."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

_PKG_DIR = Path(__file__).resolve().parent
_LANG_DIR = _PKG_DIR / "languages"
_DATA_DIR = _PKG_DIR / "data"
_REGISTRY_PATH = _DATA_DIR / "registry.json"


class LanguageNotFoundError(KeyError):
    """Raised when a requested language code has no rule file."""


@lru_cache(maxsize=1)
def registry() -> Dict[str, dict]:
    """Return the language registry keyed by ISO 639-3 code."""
    if not _REGISTRY_PATH.exists():
        return {}
    with _REGISTRY_PATH.open(encoding="utf-8") as fh:
        entries = json.load(fh)
    return {e["code"]: e for e in entries}


def available_languages() -> List[str]:
    """Return the sorted list of language codes that have a rule file."""
    return sorted(p.stem for p in _LANG_DIR.glob("*.json"))


@lru_cache(maxsize=256)
def load_rules(code: str) -> dict:
    """Load and validate a language rule file by ISO 639-3 code."""
    path = _LANG_DIR / f"{code}.json"
    if not path.exists():
        raise LanguageNotFoundError(
            f"No rule file for language {code!r}. "
            f"Available: {', '.join(available_languages()) or '(none yet)'}"
        )
    with path.open(encoding="utf-8") as fh:
        rules = json.load(fh)
    _validate(rules, code)
    return rules


def _validate(rules: dict, code: str) -> None:
    if "graphemes" not in rules or not isinstance(rules["graphemes"], dict):
        raise ValueError(f"Rule file {code!r} must contain a 'graphemes' mapping.")
