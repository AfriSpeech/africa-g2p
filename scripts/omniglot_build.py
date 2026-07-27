#!/usr/bin/env python3
"""Build a language rule file from an Omniglot chart spreadsheet.

Omniglot charts (https://www.omniglot.com/charts/<lang>.xls, by Simon Ager) lay out a
language's writing units as repeating triplets of rows:

    row r-2 : native-script unit(s)   (e.g. Vai syllable  ꔰ)
    row r-1 : Latin romanisation       (e.g.  gbi)
    row r   : IPA in brackets          (e.g.  [ɡ͡bi])

We parse those triplets and emit a rule file whose grapheme table maps BOTH the native
script unit AND its Latin romanisation to the same IPA — so the language can be phonemised
in either written form, with no separate romanisation step (no uroman needed).

Usage:
    python scripts/omniglot_build.py CHART.xls --code vai --name Vai [--out-raw]

Requires: pandas + xlrd (`pip install -e ".[data]"`). Omniglot content is © Simon Ager;
use per its terms and keep attribution.
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

_IPA_CELL = re.compile(r"^\[(.*)\]$")


def _txt(v) -> str:
    return "" if v is None else str(v).strip()


def _is_ipa_row(cells) -> bool:
    vals = [c for c in cells if c]
    return bool(vals) and sum(bool(_IPA_CELL.match(c)) for c in vals) >= max(1, len(vals) // 2)


def parse_chart(path: str):
    import pandas as pd

    df = pd.read_excel(path, header=None, dtype=str)
    grid = [[_txt(df.iat[r, c]) for c in range(df.shape[1])] for r in range(df.shape[0])]

    graphemes: dict[str, str] = {}
    script_units, latin_units = set(), set()
    for r, row in enumerate(grid):
        if r < 2 or not _is_ipa_row(row):
            continue
        script, latin = grid[r - 2], grid[r - 1]
        for c, cell in enumerate(row):
            m = _IPA_CELL.match(cell)
            if not m:
                continue
            ipa = m.group(1).strip()
            s, la = script[c] if c < len(script) else "", latin[c] if c < len(latin) else ""
            # skip the metadata column (language name / [code])
            if not ipa or la.lower() in ("", "vai") or re.fullmatch(r"[a-z]{2,3}", ipa):
                pass
            for unit, bucket in ((s, script_units), (la, latin_units)):
                unit = unicodedata.normalize("NFC", unit)
                if unit and unit not in graphemes:
                    graphemes[unit] = ipa
                    bucket.add(unit)
    return graphemes, sorted(script_units), sorted(latin_units)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("chart", help="path to an Omniglot .xls chart")
    ap.add_argument("--code", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--country", default=None)
    ap.add_argument("--family", default=None)
    args = ap.parse_args()

    graphemes, script_units, latin_units = parse_chart(args.chart)
    if not graphemes:
        print("No triplets parsed — is this an Omniglot chart?", file=sys.stderr)
        return 1

    rule = {
        "code": args.code,
        "name": args.name,
        "country": args.country,
        "family": args.family,
        "source": f"Omniglot chart ({Path(args.chart).name}), © Simon Ager",
        "confidence": "omniglot",
        "scripts": {"native": script_units, "latin": latin_units},
        "graphemes": graphemes,
        "diacritics": {},
        "alphabet": latin_units,
        "examples": [],
    }
    out = LANG_DIR / f"{args.code}.json"
    out.write_text(json.dumps(rule, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.name}: {len(graphemes)} units "
          f"({len(script_units)} native-script, {len(latin_units)} latin)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
