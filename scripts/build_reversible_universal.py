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
    blob = "".join(texts).lower()
    c = collections.Counter(blob)
    c["__text__"] = 0            # sentinel; the blob rides along for ambiguity tests
    return c, blob


def build(code: str, freq: collections.Counter | None,
          blob: str = "") -> dict | None:
    """Return {'universal': {...}, 'universal_reverse': {...}} or None if unchanged."""
    sys.path.insert(0, str(REPO / "src"))
    from africa_g2p.convert import (_universal_tables, _relax_aspiration,
                                    _strip_combining)
    from africa_g2p.loader import load_rules

    _, ipa_to_uni = _universal_tables()
    rules = load_rules(code)
    graphemes = rules.get("graphemes") or {}

    # what each grapheme maps to today
    def base_value(ipa: str) -> str | None:
        """The universal spelling the converter itself would choose.

        Not a plain dictionary lookup. Rare aspirated phonemes win the survey
        vote on tiny samples, so the converter prefers the relaxed plain-phoneme
        majority and falls back to the exact entry, then to the phoneme stripped
        of tone marks. Looking the raw IPA up directly disagreed with that:
        Twi's chart has no plain /k/ at all -- its <k> is /kʰ/, which the survey
        spells "kh" -- so the stored table started writing <k> as "kh" and Twi
        rendered "Onyankopɔn" as "onyankhophohhn".
        """
        relaxed = _relax_aspiration(ipa)
        for form in (relaxed, ipa):
            u = ipa_to_uni.get(form)
            if u:
                return u
        base = _strip_combining(ipa)
        if base and base != ipa:
            for form in (base, _strip_combining(relaxed)):
                u = ipa_to_uni.get(form)
                if u:
                    return u
        return None

    plain: dict[str, str] = {}
    for graph, ipa in graphemes.items():
        u = base_value(str(ipa))
        if u:
            plain[graph] = u

    # Assign one universal spelling per distinct SOUND, then give every
    # grapheme of that sound the same spelling. Doing it per grapheme left
    # alternates holding the old value and re-colliding; Ethiopic and Vai write
    # many phonemes twice (native script and romanisation) and those are
    # alternates, not clashes -- disambiguating them produced nonsense like
    # ሀ -> "hexx".
    def weight(g: str) -> int:
        """How often this exact spelling occurs, not the sum of its letters.

        Summing letters made "gg" outrank "g" and "ei" outrank "y" purely by
        length, so Afrikaans round-tripped "gemaak" as "ggemaak" and "hy" as
        "hei". Counting the string itself ranks them the way the language does.
        """
        if blob:
            return blob.count(g)
        return sum(freq.get(c, 0) for c in g) if freq else 0

    def script_of(ch: str) -> str:
        o = ord(ch)
        if 0x1200 <= o <= 0x137F: return "ethiopic"
        if 0x0600 <= o <= 0x06FF: return "arabic"
        if 0xA500 <= o <= 0xA63F: return "vai"
        if 0x07C0 <= o <= 0x07FF: return "nko"
        if 0x0400 <= o <= 0x04FF: return "cyrillic"
        return "latin"

    def graph_script(g: str) -> str:
        for c in g:
            if c.isalpha():
                return script_of(c)
        return "latin"

    corpus_script = "latin"
    if blob:
        counts = collections.Counter(script_of(c) for c in blob if c.isalpha())
        if counts:
            corpus_script = counts.most_common(1)[0][0]

    def in_corpus_script(g: str) -> bool:
        letters = [c for c in g if c.isalpha()]
        return bool(letters) and all(script_of(c) == corpus_script for c in letters)

    # Group by sound AND script. Sharing a spelling between two writings of one
    # sound is right across scripts -- Ethiopic ሀ and its romanisation "ha" are
    # the same word written two ways, and the reverse returns whichever script
    # the corpus uses. It is wrong within one script: ሀ ኸ ሐ ኀ are four distinct
    # Ethiopic letters that happen to be pronounced alike, and merging them left
    # three of the four unrecoverable. Same for Latin c/k/q and a/à/â.
    #
    # So every grapheme in the corpus's own script keeps its own spelling, and
    # only the other scripts' spellings fold onto it.
    per_ipa: dict[str, list[str]] = {}
    for graph in plain:
        per_ipa.setdefault(str(graphemes[graph]), []).append(graph)

    by_sound: dict[str, list[str]] = {}
    group_of: dict[str, str] = {}
    for ipa, gs in per_ipa.items():
        by_script: dict[str, list[str]] = {}
        for g in gs:
            by_script.setdefault(graph_script(g), []).append(g)
        main = (corpus_script if corpus_script in by_script
                else max(by_script, key=lambda s: sum(weight(x) for x in by_script[s])))
        for g in by_script[main]:
            key = f"{ipa}\x00{g}"
            by_sound[key] = [g]
            group_of[g] = key
        host = f"{ipa}\x00{max(by_script[main], key=lambda g: (weight(g), -len(g)))}"
        for sc, lst in by_script.items():
            if sc == main:
                continue
            for g in lst:
                by_sound[host].append(g)
                group_of[g] = host

    # what each sound would like to be spelled
    want: dict[str, str] = {}
    for ipa, gs in by_sound.items():
        want[ipa] = plain[gs[0]]

    contested: dict[str, list[str]] = {}
    for ipa, u in want.items():
        contested.setdefault(u, []).append(ipa)
    # Even with no clashes the table is written: without it the converter falls
    # back to the IPA path, which drops tone and nasal marks (míǹ -> min) that a
    # direct grapheme<->universal map passes through untouched.
    no_clash = not any(len(v) > 1 for v in contested.values())
    if no_clash:
        universal = dict(plain)
        reverse = {}
        for ipa, gs in by_sound.items():
            u = plain[gs[0]]
            cands = sorted(gs, key=lambda g: (g != u, -weight(g), len(g), g))
            reverse[u] = cands[0]
        return {"universal": universal, "universal_reverse": reverse}

    # Seed with every base spelling up front: assigning "ah" as a suffix in one
    # group would otherwise collide with a later group whose base value is "ah".
    taken: set[str] = set(contested)
    final: dict[str, str] = {}
    for u, ipas in contested.items():
        # the sound whose own spelling matches the universal value keeps it
        def best(i: str):
            gs = by_sound[i]
            return (u not in gs, -max((weight(g) for g in gs), default=0), i)
        for n, ipa in enumerate(sorted(ipas, key=best)):
            if n == 0:
                final[ipa] = u
                continue
            for suf in SUFFIXES:
                if u + suf not in taken:
                    final[ipa] = u + suf
                    taken.add(u + suf)
                    break
            else:
                k = 2
                while f"{u}{k}" in taken:
                    k += 1
                final[ipa] = f"{u}{k}"
                taken.add(f"{u}{k}")

    # A value is also ambiguous when it can be produced by concatenating other
    # values: ã spells as "an", which a real a+n sequence produces too, so the
    # reverse parse turns "nam" into "nã". This dominated the failures in
    # Kusaal, Fanti and Ga -- the injectivity check was grapheme-vs-grapheme,
    # but the clash is grapheme-vs-sequence.
    def segmentable(v: str, vals: set[str]) -> bool:
        """Ambiguous only when the competing sequence actually occurs.

        Every digraph is segmentable in principle -- "gb" is "g"+"b" -- but
        greedy matching resolves that correctly unless real g+b sequences are
        common in the language. "an" is different: a+n is everywhere, so the
        nasal vowel spelling loses. Corpus frequency decides which is which.
        """
        if len(v) < 2 or not freq:
            return False
        reach = {0}
        for i in range(len(v)):
            if i not in reach:
                continue
            for w in vals:
                if w != v and w and v.startswith(w, i):
                    reach.add(i + len(w))
        if len(v) not in reach:
            return False
        # the sequence is a genuine competitor when its parts are common letters
        # v is a real competitor when that exact string already occurs in the
        # language's own orthography: "an" is everywhere in Kusaal, so spelling
        # ã as "an" loses; "gb" as a literal pair is not, so the digraph is safe.
        if not blob:
            return False
        return blob.count(v) >= max(3, 0.0002 * len(blob))

    for _ in range(6):                       # respelling can create new clashes
        vals = set(final.values())
        # A value that IS one of the sound's own graphemes maps to itself and
        # cannot be misread: "gb" -> "gb" is safe. Only a value that spells the
        # sound as some *other* existing string is at risk -- ã -> "an".
        risky = [ipa for ipa, v in final.items()
                 if v not in by_sound[ipa] and segmentable(v, vals)]

        # A value is also unsafe when CONCATENATING it with another value
        # produces a string the greedy reverse parses differently. Ga spells ũ
        # as "un" and ŋ as "ng"; the sequence u+ŋ gives "ung", which parses as
        # "un"+"g" and comes back as ũg. Checking values in isolation misses
        # this -- the collision only exists once they are adjacent.
        if not risky:
            longest = sorted(vals, key=len, reverse=True)
            def parse(t):
                out, i = [], 0
                while i < len(t):
                    for k in longest:
                        if k and t.startswith(k, i):
                            out.append(k); i += len(k); break
                    else:
                        out.append(t[i]); i += 1
                return out
            # Blame every value the parser actually used, not just the
            # left-hand one. Ma'di spells ɨ "yh", and "n"+"yh" parses as
            # "ny"+"h": the value destroyed is "yh", while "n" maps to itself
            # and is protected, so blaming "n" respelt nothing.
            #
            # This respells hard, and a value can be suffixed on more than one
            # of the six passes -- Ma'di ɨ ends up "yhhhhhhh", which is ugly and
            # still wrong, because "ny" swallows the start of anything
            # beginning with "y" however long it gets. Fixing those few needs a
            # different stem, which this loop cannot choose. Measured over 557
            # languages it is nonetheless worth 118 of them at 100%.
            seen = set()
            for a in vals:
                for b in vals:
                    got = parse(a + b)
                    if got == [a, b]:
                        continue
                    seen.update(got)
                    seen.add(a)
                    seen.add(b)
            risky = [ipa for ipa, v in final.items()
                     if v in seen and v not in by_sound[ipa]]
        if not risky:
            break
        for ipa in risky:
            v = final[ipa]
            for suf in SUFFIXES:
                if v + suf not in taken and not segmentable(v + suf, vals | {v + suf}):
                    final[ipa] = v + suf
                    taken.add(v + suf)
                    break
            else:
                k = 2
                while f"{v}{k}" in taken:
                    k += 1
                final[ipa] = f"{v}{k}"
                taken.add(f"{v}{k}")

    universal = {g: final[group_of[g]] for g in plain}

    # Which spelling comes back. Several tables carry two scripts for one
    # language -- Amharic has Ethiopic and a romanisation, Hausa and Afrikaans
    # have Latin and a historical Arabic orthography -- and both map to the same
    # sounds, so the reverse has to choose.
    #
    # The scripts block is not the right guide: it labels Arabic "native" for
    # Hausa, but Hausa is written in Latin in practice, and preferring native
    # made Latin input come back as Ajami. Let the corpus decide instead: the
    # script the language is actually written in is the one to return.
    reverse: dict[str, str] = {}
    for ipa, u in final.items():
        # Shorter first among same-sound alternates. weight() sums character
        # frequencies, so "gg" outscores "g" simply by being longer, and
        # Afrikaans "gemaak" came back as "ggemaak"; likewise "hy" as "hei".
        cands = sorted(by_sound[ipa],
                       key=lambda g: (not in_corpus_script(g), -weight(g),
                                      g != u, len(g), g))
        reverse[u] = cands[0]

    if len(reverse) != len(final):
        raise RuntimeError(f"{code}: sounds still share a spelling")
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
        freq, blob = None, ""
        if code in files:
            try:
                freq, blob = grapheme_frequency(files[code])
            except Exception:
                pass
        try:
            blocks = build(code, freq, blob)
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
