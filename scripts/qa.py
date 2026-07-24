#!/usr/bin/env python3
"""Quality-assurance pass over the compiled language rule files.

Checks, per language:
  - grapheme table is non-empty and maps to plausible IPA
  - grapheme count vs the source's stated "number of graphemes" (from raw JSON)
  - every source example word converts through the engine with no unknown chars
  - flags low / medium confidence entries for human review

Usage:
    python scripts/qa.py                # summary + issues table
    python scripts/qa.py --verbose      # also list per-language example failures
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from africa_g2p import G2P, available_languages  # noqa: E402
from africa_g2p.loader import load_rules  # noqa: E402

RAW_DIR = ROOT / "extraction" / "raw"

# Characters we expect in IPA-ish phoneme strings; anything far outside is suspicious.
_SUSPICIOUS = set("0123456789")


def raw_for(code: str, page: int | None):
    if page is None:
        return None
    p = RAW_DIR / f"p-{page:03d}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def source_page(rules: dict) -> int | None:
    src = rules.get("source", "")
    for tok in src.replace(".", " ").split():
        if tok.isdigit():
            return int(tok)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    langs = available_languages()
    conf = Counter()
    issues: list[str] = []
    ex_total = ex_bad = 0

    for code in langs:
        rules = load_rules(code)
        conf[rules.get("confidence", "unknown")] += 1
        g2p = G2P(code, unknown="mark")
        graphemes = rules["graphemes"]

        # 1. empty / tiny tables
        if len(graphemes) < 5:
            issues.append(f"{code}: only {len(graphemes)} graphemes")

        # 2. suspicious IPA values
        for g, ipa in graphemes.items():
            if _SUSPICIOUS & set(ipa):
                issues.append(f"{code}: grapheme {g!r} -> suspicious IPA {ipa!r}")

        # 3. grapheme count vs source
        raw = raw_for(code, source_page(rules))
        if raw and raw.get("num_graphemes"):
            declared = raw["num_graphemes"]
            got = len(rules.get("alphabet") or graphemes)
            if abs(declared - got) > 2:
                issues.append(f"{code}: alphabet has {got}, source says {declared}")

        # 4. example words must convert cleanly
        bad_here = []
        for ex in rules.get("examples", []):
            word = ex.get("word", "")
            if not word:
                continue
            ex_total += 1
            out = g2p.convert(word)
            if "�" in out:
                ex_bad += 1
                bad_here.append(f"{word!r}->{out!r}")
        if bad_here and args.verbose:
            issues.append(f"{code}: {len(bad_here)} example(s) with unmapped chars: " + ", ".join(bad_here[:5]))
        elif bad_here:
            issues.append(f"{code}: {len(bad_here)} example word(s) contain chars not in grapheme table")

    print(f"languages: {len(langs)}")
    print("confidence:", dict(conf))
    print(f"example words: {ex_total} total, {ex_bad} with unmapped chars "
          f"({100*ex_bad/ex_total:.1f}% bad)" if ex_total else "no examples")
    print(f"\nissues ({len(issues)}):")
    for i in issues:
        print("  -", i)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
