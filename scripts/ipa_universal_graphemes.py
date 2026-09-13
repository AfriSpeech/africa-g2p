#!/usr/bin/env python3
"""Survey every language chart in the package and derive, for each IPA value, the
grapheme(s) most commonly used to write it — a "universal" grapheme set.

Method
------
For each language file we treat the `graphemes` mapping as (grapheme -> IPA). A language
votes **once per distinct grapheme** it uses for a given IPA value, so a language that
lists allophonic variants (e.g. `g`/`gw` for ɡ) does not get extra weight. Ties are broken
by raw row count, then lexicographically, so the output is deterministic.

Two levels of votes are kept for every IPA value:
  * `votes`  — exact grapheme (unicode-for-unicode), per-language counts
  * `base`   — the same votes collapsed to the base letter (combining marks stripped),
               e.g. a, à, á, ạ all count as `a`. Useful for building a plain Latin
               orthography from a non-diacritic set.

Output
------
Writes `src/africa_g2p/data/ipa_universal_graphemes.json`:

    {
      "meta": {...},
      "phonemes": {
        "m": {
          "grapheme": "m",            # winning exact grapheme
          "grapheme_langs": 366,     # languages voting for it
          "langs": 409,              # languages with any grapheme for this IPA
          "votes":  {"m": 366, "M": 12, ...},   # exact grapheme -> lang count
          "base":   {"m": 378, ...},             # base letter -> lang count
          "base_grapheme": "m"                   # winning base letter
        },
        ...
      }
    }

Usage:
    python scripts/ipa_universal_graphemes.py
"""
from __future__ import annotations

import json
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANG_DIR = ROOT / "src" / "africa_g2p" / "languages"
OUT = ROOT / "src" / "africa_g2p" / "data" / "ipa_universal_graphemes.json"


def base_letter(g: str) -> str:
    """Strip combining marks so à/á/ạ all count as `a`. Non-Latin (e.g. Arabic,
    Ethiopic, Vai) graphemes are untouched beyond their own combining marks."""
    return "".join(c for c in unicodedata.normalize("NFD", g) if unicodedata.combining(c) == 0)


def main() -> int:
    if not LANG_DIR.exists():
        print(f"language dir not found: {LANG_DIR}", file=sys.stderr)
        return 1

    files = sorted(LANG_DIR.glob("*.json"))
    # ipa -> grapheme -> set(lang codes)
    exact: dict[str, defaultdict[str, set]] = defaultdict(lambda: defaultdict(set))
    rows: dict[str, dict[str, int]] = defaultdict(Counter)  # ipa -> grapheme -> raw rows
    lang_count: Counter = Counter()  # ipa -> how many languages mention it at all

    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        lang = data.get("code") or path.stem
        for g, ipa in data.get("graphemes", {}).items():
            if not ipa:
                continue
            exact[ipa][g].add(lang)
            rows[ipa][g] += 1
            lang_count[ipa] += 1

    phonemes = {}
    for ipa in sorted(exact):
        gset = exact[ipa]
        votes = {g: len(langs) for g, langs in gset.items()}
        winner = _pick(votes, rows[ipa])

        base: dict[str, int] = Counter()
        for g, n in votes.items():
            base[base_letter(g)] += n
        base_winner = _pick(dict(base), base)

        phonemes[ipa] = {
            "grapheme": winner,
            "grapheme_langs": votes[winner],
            "langs": lang_count.get(ipa, 0),
            "votes": votes,
            "base": dict(base),
            "base_grapheme": base_winner,
        }

    out = {
        "meta": {
            "description": (
                "Universal grapheme set: for each IPA value, the grapheme most commonly "
                "used to write it across the language charts in this package."
            ),
            "language_files": len(files),
            "phonemes": len(phonemes),
            "method": (
                "one vote per language per distinct (grapheme, IPA) pair; ties broken "
                "by raw row count then lexicographically"
            ),
        },
        "phonemes": phonemes,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"scanned {len(files)} languages, {len(phonemes)} distinct IPA values")
    print()
    print("most common exact graphemes per IPA (top 40 by number of languages):")
    print(f"{'IPA':<10}{'grapheme':<12}{'langs':>6}  top graphemes")
    top = sorted(phonemes.items(), key=lambda kv: -kv[1]["grapheme_langs"])
    for ipa, v in top[:40]:
        order = sorted(v["votes"].items(), key=lambda kv: (-kv[1], _sort_key(kv[0])))
        topg = " ".join(f"{g}:{n}" for g, n in order[:5])
        print(f"{ipa:<10}{v['grapheme']:<12}{v['grapheme_langs']:>6}  {topg}")

    print()
    print("50 phonemes with NO shared winning grapheme (one language each):")
    rare = sorted((ipa, v) for ipa, v in phonemes.items() if v["langs"] == 1)
    for ipa, v in rare[:50]:
        print(f"{v['grapheme']:<10}{ipa:<10}{v['langs']}")

    print()
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


def _pick(votes: dict[str, int], rows: dict[str, int]) -> str:
    """Highest language-vote count; ties broken by raw row count, then lexicographic."""
    best = max(votes.values()) if votes else 0
    cands = [g for g, n in votes.items() if n == best]
    if len(cands) > 1:
        cands = [g for g in cands if rows.get(g, 0) == max(rows.get(g, 0) for g in cands)]
    return min(sorted(cands), key=lambda g: _sort_key(g))


def _sort_key(g: str) -> tuple:
    # ASCII-ish graphemes first, then by codepoints — deterministic, script-friendly.
    return (base_letter(g) not in "abcdefghijklmnopqrstuvwxyz", len(g), g)


def _ipa(w: str) -> str:
    return w if w else "?"


if __name__ == "__main__":
    raise SystemExit(main())