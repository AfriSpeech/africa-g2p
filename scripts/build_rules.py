#!/usr/bin/env python3
"""Compile vision-extracted raw JSON (extraction/raw/*.json) into validated
per-language rule files (src/africa_g2p/languages/*.json) and the registry.

Usage:
    python scripts/build_rules.py [--raw extraction/raw] [--force]

Skips pages flagged `is_language_page: false`. Hand-verified rule files (confidence
"hand-verified") are never overwritten unless --force is given.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANG_DIR = ROOT / "src" / "africa_g2p" / "languages"
REGISTRY = ROOT / "src" / "africa_g2p" / "data" / "registry.json"


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"\(.*?\)", "", s).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "unknown"


# Greek letters that stand in for IPA letters in the scanned sources. β, θ and χ are
# genuine IPA codepoints and are deliberately absent here.
_LOOKALIKES = {
    # Greek letters standing in for IPA letters. β, θ and χ are genuine IPA and absent here.
    "γ": "ɣ",  # gamma -> IPA voiced velar fricative U+0263
    "ε": "ɛ",  # epsilon -> IPA open e U+025B
    "ι": "ɪ",  # iota -> IPA small capital i U+026A
    "α": "ɑ",  # alpha -> IPA script a U+0251
    # Capital letters standing in for IPA symbols. IPA has no uppercase letters; the
    # small-capital symbols (ɪ ʁ ɢ) are their own codepoints.
    "Ɂ": "ʔ",  # U+0241 capital glottal stop -> U+0294
    "Ɩ": "ɪ",  # U+0196 capital iota -> U+026A
}


def norm_ipa(s: str) -> str:
    """Normalize common IPA glyph variants to their canonical codepoints.

    Also strips the phonetic brackets and slashes that several source charts wrap every
    value in ("[a]", "/k͡p/"), and folds Greek and capital-letter lookalikes to the IPA
    codepoint they stand for. Left in place these end up inside phoneme values, where they
    are indistinguishable from real symbols to any downstream consumer.
    """
    s = (
        s.replace("g", "ɡ")   # ASCII g (U+0067) -> IPA script g (U+0261)
        .replace(":", "ː")    # ASCII colon -> IPA length mark
        .replace("'", "ˈ")    # ASCII apostrophe stress -> IPA primary stress
    )
    s = re.sub(r"^[\[/](.*)[\]/]$", r"\1", s.strip())
    s = s.replace("[", "").replace("]", "")
    return "".join(_LOOKALIKES.get(ch, ch) for ch in s)


def to_rule_file(raw: dict) -> dict | None:
    if not raw.get("is_language_page", True):
        return None
    graphemes = {}
    for row in raw.get("graphemes", []):
        g = (row.get("grapheme") or "").strip()
        p = norm_ipa((row.get("phoneme") or "").strip())
        if g and p and g not in graphemes:
            graphemes[g] = p
    if not graphemes:
        return None

    diacritics = {}
    for d in raw.get("diacritics", []):
        mark = d.get("mark", "")
        if mark.startswith("U+"):
            try:
                mark = chr(int(mark[2:], 16))
            except ValueError:
                continue
        if mark and d.get("ipa"):
            diacritics[mark] = d["ipa"]

    code = (raw.get("iso639_3") or "").strip().lower() or slug(raw.get("language", ""))
    return {
        "code": code,
        "name": raw.get("language", code),
        "country": raw.get("country"),
        "family": raw.get("family"),
        "source": f"Hartell 1993, Alphabets of Africa (UNESCO), p. {raw.get('page')}",
        "confidence": raw.get("confidence", "extracted"),
        "graphemes": graphemes,
        "diacritics": diacritics,
        "tones": raw.get("tones", {}),
        "notes": raw.get("notes", ""),
        "alphabet": raw.get("alphabet", []),
        "examples": raw.get("examples", []),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", default=str(ROOT / "extraction" / "raw"))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    LANG_DIR.mkdir(parents=True, exist_ok=True)
    written = skipped = 0

    # First pass: compile all rules and detect which base codes collide.
    rules = []
    for rawpath in sorted(Path(args.raw).glob("*.json")):
        raw = json.loads(rawpath.read_text(encoding="utf-8"))
        rule = to_rule_file(raw)
        if rule is None:
            skipped += 1
            continue
        rules.append(rule)
    base_counts = Counter(r["code"] for r in rules)

    # Second pass: colliding codes (same language, different national orthography)
    # are disambiguated by country slug, e.g. yor-nigeria vs yor-benin.
    used = Counter()
    for rule in rules:
        code = rule["code"]
        if base_counts[code] > 1:
            suffix = slug(rule.get("country") or "")
            code = f"{code}-{suffix}" if suffix else code
            used[code] += 1
            if used[code] > 1:  # still colliding (same code+country) -> number
                code = f"{code}{used[code]}"
        rule["code"] = code

        out = LANG_DIR / f"{code}.json"
        if out.exists() and not args.force:
            existing = json.loads(out.read_text(encoding="utf-8"))
            if existing.get("confidence") == "hand-verified":
                skipped += 1
                continue

        out.write_text(json.dumps(rule, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written += 1

    # Registry is derived from the rule files themselves (the source of truth),
    # so hand-verified languages without a raw file are preserved.
    registry = [
        _reg(json.loads(p.read_text(encoding="utf-8")))
        for p in sorted(LANG_DIR.glob("*.json"))
    ]
    registry.sort(key=lambda e: e["code"])
    REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {written} rule files, skipped {skipped}; registry has {len(registry)} langs")
    return 0


def _reg(rule: dict) -> dict:
    return {
        "code": rule["code"],
        "name": rule.get("name"),
        "country": rule.get("country"),
        "family": rule.get("family"),
        "confidence": rule.get("confidence"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
