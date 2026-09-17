#!/usr/bin/env python3
"""Make each language's grapheme -> universal mapping injective, and store both directions.

Today the mapping is derived: a language's chart maps grapheme -> IPA, then a
shared table maps IPA -> universal grapheme. That is already per-language -- 532
graphemes take different universal values in different languages -- but it is
not injective. Twi writes both `e` and `ɛ`, and both land on `e`, so the
universal form cannot be turned back into Twi.

This script resolves those clashes per language. Within one language, every
grapheme gets a distinct universal spelling; across languages nothing changes
unless that language actually had a clash. Collisions are common: 91% of the
740 languages have at least one, most have 3-5, and a few click and Ethiopic
languages have over 100.

Which grapheme keeps the plain spelling is decided by frequency in that
language's own corpus, so the common one stays readable and the marked one
takes the longer form. Suffixes are tried in order and the first that is free
*within that language* wins -- what another language uses is irrelevant, since
reverse conversion is always language-scoped.

    python scripts/build_reversible_universal.py --codes twi ewe dag
    python scripts/build_reversible_universal.py --all
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LANG_DIR = REPO / "src" / "africa_g2p" / "languages"
CORPUS = "AfriSpeech/africa-corpus"

# Tried in order; the first free within the language wins. "h" first because a
# trailing h is rare word-internally in these orthographies, so it reads as a
# modifier rather than a separate sound.
SUFFIXES = ("h", "x", "q", "hh", "xx")


def hf_token() -> str:
    t = os.environ.get("HF_TOKEN")
    return t or (Path.home() / ".cache/huggingface/token").read_text().strip()


def corpus_files() -> dict[str, str]:
    req = urllib.request.Request(f"https://huggingface.co/api/datasets/{CORPUS}",
                                 headers={"Authorization": f"Bearer {hf_token()}"})
    out = {}
    for s in json.load(urllib.request.urlopen(req, timeout=120))["siblings"]:
        m = re.match(r"^(.*)_([a-z]{3})_v\d+\.csv$", s["rfilename"])
        if m:
            out.setdefault(m.group(2), s["rfilename"])
    return out


def grapheme_frequency(fname: str, nbytes: int = 200_000) -> collections.Counter:
    """How often each character occurs in that language's real text."""
    url = (f"https://huggingface.co/datasets/{CORPUS}/resolve/main/"
           + urllib.parse.quote(fname))
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {hf_token()}",
                                               "Range": f"bytes=0-{nbytes}"})
    raw = urllib.request.urlopen(req, timeout=120).read().decode("utf-8", "replace")
    texts = [l.split(",", 2)[2] for l in raw.splitlines()[1:] if l.count(",") >= 2]
    return collections.Counter("".join(texts).lower())


def build(code: str, freq: collections.Counter | None) -> dict | None:
    """Return {'universal': {...}, 'universal_reverse': {...}} or None if unchanged."""
    sys.path.insert(0, str(REPO / "src"))
    from africa_g2p.convert import _universal_tables
    from africa_g2p.loader import load_rules

    _, ipa_to_uni = _universal_tables()
    graphemes = load_rules(code).get("graphemes") or {}

    # what each grapheme maps to today
    plain: dict[str, str] = {}
    for graph, ipa in graphemes.items():
        u = ipa_to_uni.get(str(ipa))
        if u:
            plain[graph] = u

    clashes: dict[str, list[str]] = {}
    for graph, u in plain.items():
        clashes.setdefault(u, []).append(graph)
    clashes = {u: gs for u, gs in clashes.items() if len(gs) > 1}
    if not clashes:
        return None                      # already injective, leave it alone

    def weight(g: str) -> int:
        return sum(freq.get(c, 0) for c in g) if freq else 0

    def rank(u: str):
        """Who keeps the plain spelling: the grapheme that already *is* it.

        Frequency alone gives backwards results -- in Fante ɔ outnumbers o, so
        ɔ would take "o" and plain o would become "oh". Preferring the grapheme
        identical to the universal value keeps the obvious reading, and
        frequency only breaks ties among the rest.
        """
        def key(g: str):
            return (g != u, -weight(g), len(g), g)
        return key

    taken = set(plain.values())
    universal = dict(plain)
    for u, group in clashes.items():
        # the most frequent grapheme keeps the plain spelling
        ordered = sorted(group, key=rank(u))
        for graph in ordered[1:]:
            for suf in SUFFIXES:
                cand = u + suf
                if cand not in taken:
                    universal[graph] = cand
                    taken.add(cand)
                    break
            else:
                n = 2
                while f"{u}{n}" in taken:
                    n += 1
                universal[graph] = f"{u}{n}"
                taken.add(f"{u}{n}")

    reverse = {v: k for k, v in universal.items()}
    if len(reverse) != len(universal):
        raise RuntimeError(f"{code}: still not injective after disambiguation")
    return {"universal": universal, "universal_reverse": reverse}


_PLAIN_CACHE: dict[str, dict[str, str]] = {}


def plain_of(code: str, graph: str) -> str | None:
    """What this grapheme mapped to before disambiguation."""
    if code not in _PLAIN_CACHE:
        sys.path.insert(0, str(REPO / "src"))
        from africa_g2p.convert import _universal_tables
        from africa_g2p.loader import load_rules
        _, ipa_to_uni = _universal_tables()
        g = load_rules(code).get("graphemes") or {}
        _PLAIN_CACHE[code] = {k: ipa_to_uni.get(str(v)) for k, v in g.items()}
    return _PLAIN_CACHE[code].get(graph)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, str(REPO / "src"))
    from africa_g2p import available_languages

    files = corpus_files()
    codes = args.codes or (available_languages() if args.all else [])
    if not codes:
        ap.error("pass --codes or --all")

    changed = skipped = 0
    for code in codes:
        freq = None
        if code in files:
            try:
                freq = grapheme_frequency(files[code])
            except Exception:
                pass
        try:
            blocks = build(code, freq)
        except Exception as exc:
            print(f"  {code:<5} ERROR {type(exc).__name__}: {exc}", flush=True)
            continue
        if blocks is None:
            skipped += 1
            continue
        n_dis = sum(1 for g, u in blocks["universal"].items() if plain_of(code, g) != u)
        if args.dry_run:
            ex = {g: u for g, u in blocks["universal"].items() if plain_of(code, g) != u}
            print(f"  {code:<5} {n_dis:>3} respelt  {dict(list(ex.items())[:6])}", flush=True)
        else:
            path = LANG_DIR / f"{code}.json"
            d = json.loads(path.read_text(encoding="utf-8"))
            d.update(blocks)
            path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  {code:<5} {n_dis:>3} respelt", flush=True)
        changed += 1

    print(f"\n{changed} languages given an injective table, "
          f"{skipped} already injective")


if __name__ == "__main__":
    main()
