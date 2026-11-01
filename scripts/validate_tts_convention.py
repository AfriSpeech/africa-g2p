#!/usr/bin/env python3
"""Check rule files against docs/IPA_CONVENTION.md (the machine-checkable parts).

    python3 scripts/validate_tts_convention.py src/africa_g2p/languages/twi.json ...
    python3 scripts/validate_tts_convention.py --cross src/africa_g2p/languages/{twi,fat,ewe,gaa,dag}.json   # also cross-language symbol report

Exit code 1 if any file violates the convention.
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

CONSONANTS = set(
    "pbtdʈɖcɟkɡqɢʔmɱnɳɲŋɴʙrʀⱱɾɽɸβfvθðszʃʒʂʐçʝxɣχʁħʕhɦɬɮʋɹɻjɰlɭʎʟɓɗʄɠʛwʍɥɕʑɺɧ")
VOWELS = set("iyɨʉɯuɪʏʊeøɘɵɤoəɛœɜɞʌɔæɐaɶɑɒ")
TIE = "͡"
NASAL = "̃"
MODIFIERS = {"ʷ", "ʲ"}
TIED_OK = {"t͡s", "d͡z", "t͡ʃ", "d͡ʒ", "t͡ɕ", "d͡ʑ", "k͡p", "ɡ͡b", "ŋ͡m", "p͡f", "b͡v"}
LIGATURES = set("ʧʤʦʣʨʥ")
ORTHO_VOWEL_LETTERS = set("aeiouɛɔəɨ")


def parse_phoneme(v: str) -> str | None:
    """Return None if v is exactly one phoneme per the convention, else a reason."""
    if not v:
        return "empty value"
    if unicodedata.normalize("NFC", v) != v:
        return "not NFC"
    if "g" in v:
        return "ASCII g (use ɡ U+0261)"
    if any(c in LIGATURES for c in v):
        return "ligature affricate"
    # NFD splits precomposed IPA letters such as ç (c + U+0327); put them back.
    d = unicodedata.normalize("NFD", v).replace("c\u0327", "ç")
    i = 0
    base = d[i]
    if base not in CONSONANTS | VOWELS:
        return f"non-IPA or non-segment symbol {base!r} (U+{ord(base):04X})"
    i += 1
    if i < len(d) and d[i] == TIE:
        if i + 1 >= len(d):
            return "dangling tie bar"
        pair = unicodedata.normalize("NFC", d[: i + 2])
        if pair not in TIED_OK:
            return f"unexpected tied pair {pair!r}"
        i += 2
    if i < len(d) and d[i] == NASAL:
        if base not in VOWELS:
            return "nasal tilde on a consonant"
        i += 1
    if i < len(d) and d[i] in MODIFIERS:
        if base in VOWELS:
            return "secondary articulation on a vowel"
        i += 1
    if i != len(d):
        rest = d[i:]
        names = ", ".join(f"U+{ord(c):04X}" for c in rest)
        return f"more than one phoneme or extra marks: {rest!r} ({names})"
    return None


def check_file(path: Path) -> tuple[list[str], dict]:
    rules = json.loads(path.read_text(encoding="utf-8"))
    errs = []
    g = rules.get("graphemes", {})
    for k, v in sorted(g.items()):
        why = parse_phoneme(v)
        if why:
            errs.append(f"{path.stem}: {k!r} -> {v!r}: {why}")
        kk = k.lower()
        if len(kk) >= 2 and all(c in ORTHO_VOWEL_LETTERS for c in kk):
            errs.append(f"{path.stem}: {k!r}: vowel sequence as a table entry")
    for k, v in sorted(rules.get("diacritics", {}).items()):
        if v not in ("", NASAL):
            errs.append(f"{path.stem}: diacritic {k!r} -> {v!r}: must be '' or U+0303")
    return errs, g


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--cross", action="store_true", help="print grapheme->IPA across files")
    args = ap.parse_args()
    all_errs, tables = [], {}
    for f in args.files:
        errs, g = check_file(Path(f))
        all_errs += errs
        tables[Path(f).stem] = g
    for e in all_errs:
        print("ERROR", e)
    if args.cross:
        keys = sorted({k for g in tables.values() for k in g}, key=lambda k: (len(k), k))
        langs = list(tables)
        print("grapheme".ljust(10) + "".join(l.ljust(8) for l in langs))
        for k in keys:
            row = [tables[l].get(k, "·") for l in langs]
            flag = "  <- differs" if len({r for r in row if r != "·"}) > 1 else ""
            print(k.ljust(10) + "".join(r.ljust(8) for r in row) + flag)
    print(f"{len(args.files)} files, {len(all_errs)} errors")
    return 1 if all_errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
