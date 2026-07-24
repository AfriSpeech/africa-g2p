#!/usr/bin/env python3
"""Enrich the language registry with canonical metadata from `afriso`.

Adds, per language (where resolvable): canonical ISO 639-3 code, language family,
region(s), and alternative names. The rule-file `code` (which may carry a country
suffix like `hau-niger`) is kept as the primary key; `iso639_3` records the canonical
standard code for interoperability. Non-resolvable entries are left as-is and reported.

Usage:
    python scripts/enrich_registry.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
REGISTRY = ROOT / "src" / "africa_g2p" / "data" / "registry.json"

import afriso  # noqa: E402


def resolve(name: str):
    for cand in (name, re.split(r"[(/]", name)[0].strip()):
        try:
            return afriso.get(cand)
        except Exception:
            continue
    return None


def main() -> int:
    entries = json.loads(REGISTRY.read_text(encoding="utf-8"))
    resolved = unresolved = 0
    for e in entries:
        lang = resolve(e.get("name", ""))
        if lang is None:
            e.setdefault("iso639_3", None)
            unresolved += 1
            continue
        e["iso639_3"] = lang.iso639_3
        e["family"] = lang.family or e.get("family")
        e["regions"] = list(lang.regions)
        e["alt_names"] = list(lang.alt_names)
        e["glottocode"] = lang.glottocode
        resolved += 1

    REGISTRY.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"enriched {resolved}/{len(entries)} entries with afriso metadata; "
          f"{unresolved} unresolved (kept as-is)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
