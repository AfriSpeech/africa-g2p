#!/usr/bin/env python3
"""Build rule files for Ethiopic-script (abugida) languages from Omniglot charts.

Omniglot's Ethiopic charts lay the fidel out as a regular grid: a header gives the seven
vowel orders and their IPA, then each consonant occupies a row-pair — the top row holds the
seven syllable characters, the row below holds the consonant's IPA (in the label column) and
the syllable romanisations. This regularity makes a dedicated parser far more reliable than
an LLM for these large grids.

For each syllable character we emit  char -> consonant_ipa + vowel_ipa  and a romanisation
pair  char -> latin. The Latin romanisations are added as graphemes too, so Ethiopic text and
its transliteration both phonemise.

Usage:
    python scripts/ethiopic_build.py CHART.xls --code amh --name Amharic [--country ET]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANG_DIR = ROOT / "src" / "africa_g2p" / "languages"

_ETHIOPIC = range(0x1200, 0x1380)
_BRACKET = re.compile(r"^\[(.*)\]$")


def _txt(v) -> str:
    return "" if v is None or str(v) == "nan" else str(v).strip()


def is_ethiopic(ch: str) -> bool:
    return bool(ch) and any(ord(c) in _ETHIOPIC for c in ch)


def _first_alt(ipa: str) -> str:
    ipa = _BRACKET.match(ipa).group(1) if _BRACKET.match(ipa) else ipa
    return ipa.split("/")[0].strip()


def parse_ethiopic(path: str):
    import pandas as pd
    xl = pd.ExcelFile(path)
    sheet = "Alphabet" if "Alphabet" in xl.sheet_names else xl.sheet_names[0]
    df = xl.parse(sheet, header=None, dtype=str)
    grid = [[_txt(df.iat[r, c]) for c in range(df.shape[1])] for r in range(df.shape[0])]
    ncol = df.shape[1]

    # 1) Vowel-order IPA header: the row with the most bracketed cells.
    hdr = max(range(len(grid)), key=lambda r: sum(bool(_BRACKET.match(c)) for c in grid[r]))
    vowel_ipa = {c: _first_alt(grid[hdr][c]) for c in range(ncol) if _BRACKET.match(grid[hdr][c])}
    if not vowel_ipa:
        return {}, {}
    vowel_cols = sorted(vowel_ipa)

    graphemes: dict[str, str] = {}
    romanization: dict[str, str] = {}
    # 2) Walk row-pairs below the header. Top row = syllable chars; next row = IPA/romanisation.
    for r in range(hdr + 1, len(grid) - 1):
        top, bot = grid[r], grid[r + 1]
        if not any(is_ethiopic(top[c]) for c in vowel_cols if c < len(top)):
            continue
        for label_col in {c - 1 for c in vowel_cols}:
            if label_col < 0 or label_col >= len(bot):
                continue
            m = _BRACKET.match(bot[label_col])
            cons_ipa = _first_alt(bot[label_col]) if m else None
            if cons_ipa is None:
                continue
            block = [c for c in vowel_cols if c - 1 == label_col or (c - 7 <= label_col < c)]
            for c in [vc for vc in vowel_cols if vc > label_col][:7]:
                ch = unicodedata.normalize("NFC", top[c]) if c < len(top) else ""
                if not is_ethiopic(ch):
                    continue
                ipa = cons_ipa + vowel_ipa[c]
                graphemes.setdefault(ch, ipa)
                latin = bot[c] if c < len(bot) else ""
                if latin and not _BRACKET.match(latin):
                    romanization.setdefault(ch, latin)
                    graphemes.setdefault(latin, ipa)
    return graphemes, romanization


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("chart")
    ap.add_argument("--code", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--country", default=None)
    ap.add_argument("--family", default=None)
    args = ap.parse_args()

    graphemes, romanization = parse_ethiopic(args.chart)
    if len(graphemes) < 20:
        print(f"Only {len(graphemes)} units parsed — not a fidel grid?", file=sys.stderr)
        return 1
    native = sorted(g for g in graphemes if is_ethiopic(g))
    latin = sorted(g for g in graphemes if not is_ethiopic(g))
    rule = {
        "code": args.code, "name": args.name, "country": args.country, "family": args.family,
        "source": f"Omniglot chart ({Path(args.chart).name}), © Simon Ager, https://omniglot.com",
        "confidence": "omniglot",
        "scripts": {"native": native, "latin": latin},
        "graphemes": graphemes, "romanization": romanization,
        "diacritics": {}, "tones": {}, "alphabet": latin, "examples": [],
    }
    out = LANG_DIR / f"{args.code}.json"
    out.write_text(json.dumps(rule, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.name}: {len(graphemes)} units ({len(native)} fidel, {len(latin)} latin, "
          f"{len(romanization)} romanisation pairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
