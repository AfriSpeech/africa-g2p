#!/usr/bin/env python3
"""Rebuild ipa_universal_graphemes.json from Gemini's per-IPA grapheme picks.

The majority-grapheme survey (scripts/ipa_universal_graphemes.py) distills each IPA
value to the most common grapheme across ~400 language charts, but its winners are
script-biased (Ethiopic syllabary glyphs, rare IPA letters, tiny samples like /tɕʰ/
-> "q"). This script takes Gemini's answer for every IPA value instead ("most common
English/Latin-style grapheme"), keeping the survey's per-IPA metadata (votes, lang
counts) for provenance and collision ordering.

Inputs:
  src/africa_g2p/data/ipa_universal_graphemes.json   (survey output, unchanged)
  <gemini_tsv>                                       (ipa\tours\tgemini\tlangs\tagree)

Output:
  Writes the JSON in place (backing up the previous file to .survey.json first).

Usage:
  python3 scripts/build_universal_from_gemini.py path/to/gemini_ipa_graphemes.tsv
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

DATA = (
    Path(__file__).resolve().parent.parent
    / "src/africa_g2p/data/ipa_universal_graphemes.json"
)


def main(tsv: str) -> None:
    gemini: dict[str, str] = {}
    for line in Path(tsv).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("ipa\t"):
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            gemini[parts[0]] = parts[2]

    data = json.loads(DATA.read_text(encoding="utf-8"))
    fallback = replaced = 0
    for ipa, entry in data["phonemes"].items():
        pick = gemini.get(ipa)
        if not pick or pick == "?":
            fallback += 1
            continue
        if pick != entry["grapheme"]:
            replaced += 1
        entry["grapheme"] = pick
        entry["grapheme_langs"] = entry["langs"]  # coverage unchanged, winner overridden
    data["meta"]["grapheme_source"] = (
        "gemini-3.6-flash verbatim picks per IPA value (English/Latin-style spelling); "
        "votes/lang counts from the 400-language ipa survey"
    )

    shutil.copyfile(DATA, DATA.with_suffix(".json.survey"))
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    miss = len(data["phonemes"]) - (len(gemini) - fallback) if False else None
    print(f"entries: {len(data['phonemes'])} | graphemes replaced: {replaced} | "
          f"kept survey winner for {fallback} ('?' or missing in gemini)")
    print(f"backup -> {DATA.with_suffix('.json.survey')}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])