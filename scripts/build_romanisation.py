#!/usr/bin/env python3
"""Romanise the non-Latin scripts with uroman instead of inventing a mapping.

The fallback table spells a letter the way most rule tables spell it. That works
for a Latin letter some other language also writes, and it is the wrong tool for
a whole script: deriving Ethiopic or Vai letter by letter from our own tables
produces a romanisation nobody uses, and risks misrepresenting the script.
uroman exists for exactly this and is built for the NLP use.

uroman is context-free over these scripts -- romanising a string character by
character gives the same answer as romanising the whole string -- which was
checked before relying on it here. So its output is baked into a lookup table
and the library keeps its empty runtime dependency list; uroman is needed only
to regenerate the data.

    pip install uroman
    python scripts/build_romanisation.py            # rewrite the table
    python scripts/build_romanisation.py --dry-run  # show what would change
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LANG_DIR = REPO / "src" / "africa_g2p" / "languages"
FALLBACK = REPO / "src/africa_g2p/data/universal_fallback.json"
CORPUS = "AfriSpeech/africa-corpus"
sys.path.insert(0, str(REPO / "src"))


def script_of(ch: str) -> str | None:
    o = ord(ch)
    if 0x1200 <= o <= 0x137F: return "ethiopic"
    if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0x08A0 <= o <= 0x08FF: return "arabic"
    if 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF: return "arabic"
    if 0xA500 <= o <= 0xA63F: return "vai"
    if 0x07C0 <= o <= 0x07FF: return "nko"
    if 0x2D30 <= o <= 0x2D7F: return "tifinagh"
    if 0x0400 <= o <= 0x04FF: return "cyrillic"
    if 0x2C80 <= o <= 0x2CFF: return "coptic"
    return None


def hf_token() -> str:
    import os
    return (os.environ.get("HF_TOKEN")
            or (Path.home() / ".cache/huggingface/token").read_text().strip())


def corpus_chars(limit: int | None = None) -> set:
    """Every non-Latin character the corpora actually contain."""
    req = urllib.request.Request(f"https://huggingface.co/api/datasets/{CORPUS}",
                                 headers={"Authorization": f"Bearer {hf_token()}"})
    files = {}
    for s in json.load(urllib.request.urlopen(req, timeout=300))["siblings"]:
        m = re.match(r"^(.*)_([a-z]{3})_v\d+\.csv$", s["rfilename"])
        if m:
            files.setdefault(m.group(2), []).append(s["rfilename"])
    seen = set()
    codes = sorted(files)[:limit] if limit else sorted(files)
    for code in codes:
        for fn in files[code]:
            try:
                url = (f"https://huggingface.co/datasets/{CORPUS}/resolve/main/"
                       + urllib.parse.quote(fn))
                req = urllib.request.Request(
                    url, headers={"Authorization": f"Bearer {hf_token()}",
                                  "Range": "bytes=0-60000"})
                raw = urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace")
            except Exception:
                continue
            for ch in raw:
                if script_of(ch):
                    seen.add(ch)
    return seen


def chart_chars() -> set:
    out = set()
    for p in LANG_DIR.glob("*.json"):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for k in (t.get("graphemes") or {}):
            for ch in k:
                if script_of(ch):
                    out.add(ch)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    import uroman as ur
    U = ur.Uroman()

    chars = chart_chars() | corpus_chars(args.limit)
    print(f"{len(chars)} non-Latin characters found in charts and corpora")

    tbl = json.loads(FALLBACK.read_text(encoding="utf-8"))
    spell = dict(tbl["spell"])
    drop = set(tbl.get("drop", []))

    added = changed = rejected = 0
    samples = []
    for ch in sorted(chars):
        try:
            r = U.romanize_string(ch)
        except Exception:
            rejected += 1
            continue
        r = "".join(c for c in unicodedata.normalize("NFD", r.lower())
                    if not unicodedata.combining(c))
        cat = unicodedata.category(ch)
        if cat.startswith("P") or cat.startswith("Z"):
            # Punctuation romanises to punctuation, not to letters: Ethiopic ፣
            # is a comma and ። a full stop. Keeping only a-z dropped them and
            # they survived into universal output as themselves.
            r = "".join(c for c in r if c in ",.;:!?'\"()-\u2014 ")
            if r and r != ch:
                if spell.get(ch) != r:
                    pass
                spell[ch] = r
                drop.discard(ch)
            continue
        if unicodedata.combining(ch) or cat == "Mn":
            # Let uroman decide rather than dropping every mark. It writes the
            # Arabic vowel points as letters -- fatha is "a", damma "u", kasra
            # "i" -- because they are the vowels, and writes nothing for sukun,
            # shadda or a tone accent. Dropping them all cost vocalised Arabic
            # its vowels: يَوْم came out "ywm" instead of "yawm".
            keep = "".join(c for c in r if "a" <= c <= "z")
            # A mark with no phonetic value gets its own name back: U+065C
            # ARABIC VOWEL SIGN DOT BELOW romanised to "dot", U+0653 MADDAH
            # ABOVE to "maddah", and U+065B INVERTED SMALL V ABOVE to "v" --
            # which reads as a plausible letter but is the word V from the
            # name. A TTS engine then says "dot" aloud mid-sentence. The real
            # vowel points do not do this: fatha gives "a", and "a" is not a
            # word in "ARABIC FATHA".
            try:
                name_words = set(unicodedata.name(ch).lower().split())
            except ValueError:
                name_words = set()
            if keep and keep not in name_words:
                spell[ch] = keep
                drop.discard(ch)
            else:
                spell.pop(ch, None)
                drop.add(ch)
            continue
        r = "".join(c for c in r if "a" <= c <= "z")
        if not r:
            if cat.startswith("L"):
                drop.add(ch)
            continue
        if len(r) > 6:
            rejected += 1
            continue
        old = spell.get(ch)
        if old is None:
            added += 1
        elif old != r:
            changed += 1
            if len(samples) < 12:
                samples.append((ch, old, r))
        spell[ch] = r
        drop.discard(ch)

    print(f"   added {added}, changed {changed}, rejected {rejected}")
    if samples:
        print("\n   examples of changes (ours -> uroman):")
        for ch, old, new in samples:
            print(f"      {ch!r} U+{ord(ch):04X}  {old!r} -> {new!r}")
    if args.dry_run:
        print("\ndry run, nothing written")
        return

    tbl["spell"] = dict(sorted(spell.items()))
    tbl["drop"] = sorted(drop)
    tbl["romanised_by_uroman"] = sorted(c for c in chars if c in spell)
    tbl["_comment"] = (
        "Last-resort spelling for a letter a language's own table does not list. "
        "A Latin letter takes the spelling the most other tables give it -- ŋ is "
        "written ng by 346 of them. A letter of a non-Latin script is romanised by "
        "uroman instead, because deriving a whole script from our own tables "
        "produces a romanisation nobody uses; uroman is context-free over these "
        "scripts, so its output bakes into this table and the library needs no "
        "runtime dependency. 'drop' lists marks the universal orthography does "
        "not write at all.")
    FALLBACK.write_text(json.dumps(tbl, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"\nwritten to {FALLBACK.relative_to(REPO)}  ({len(spell)} spellings)")


if __name__ == "__main__":
    main()
