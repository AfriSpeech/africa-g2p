#!/usr/bin/env python3
"""Measure, per language, how much survives universal -> orthography.

Converting to universal is lossy by construction: it collapses distinctions so
the same sound is written the same way everywhere. The stored per-language
tables recover most of it, but not all -- a language that writes one sound two
ways normalises to one of them, and a multi-character universal value can be
re-parsed as a sequence of shorter ones.

This reports the per-language exact-round-trip rate on real corpus text, so
consumers can see how lossy their language is rather than guessing. Output is
written to data/reversibility.json.
"""
from __future__ import annotations

import json, os, re, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from africa_g2p import GraphemeConverter, UNIVERSAL_REVERSIBLE, available_languages
from africa_g2p.convert import strip_apostrophes, plain_latin_languages
from africa_g2p.normalizer import normalize_text

CORPUS = "AfriSpeech/africa-corpus"
N = int(os.environ.get("N_SENTENCES", "60"))


def token():
    return (os.environ.get("HF_TOKEN")
            or (Path.home() / ".cache/huggingface/token").read_text().strip())


def corpus_files():
    req = urllib.request.Request(f"https://huggingface.co/api/datasets/{CORPUS}",
                                 headers={"Authorization": f"Bearer {token()}"})
    out = {}
    for s in json.load(urllib.request.urlopen(req, timeout=120))["siblings"]:
        m = re.match(r"^(.*)_([a-z]{3})_v\d+\.csv$", s["rfilename"])
        if m: out.setdefault(m.group(2), (m.group(1).replace("_", " "), s["rfilename"]))
    return out


FILES = corpus_files()


def measure(code):
    if code not in FILES:
        return None
    name, fname = FILES[code]
    url = (f"https://huggingface.co/datasets/{CORPUS}/resolve/main/"
           + urllib.parse.quote(fname))
    try:
        r = urllib.request.Request(url, headers={"Authorization": f"Bearer {token()}",
                                                 "Range": "bytes=0-90000"})
        raw = urllib.request.urlopen(r, timeout=90).read().decode("utf-8", "replace")
    except Exception:
        return None
    texts = [l.split(",", 2)[2].strip() for l in raw.splitlines()[1:]
             if l.count(",") >= 2][:N]
    texts = [t for t in texts if t]
    if len(texts) < 20:
        return None
    try:
        f = GraphemeConverter(code, UNIVERSAL_REVERSIBLE)
        b = GraphemeConverter(UNIVERSAL_REVERSIBLE, code)
    except Exception:
        return None

    exact = chars_ok = chars_tot = 0
    for t in texts:
        want = normalize_text(t)
        if f.passthrough:
            want = strip_apostrophes(want)
        try:
            back = b.convert(f.convert(t))
        except Exception:
            continue
        if back == want:
            exact += 1
        # character-level agreement, so "how lossy" is not just pass/fail
        chars_tot += len(want)
        chars_ok += sum(1 for a, c in zip(want, back) if a == c)
    return {"code": code, "name": name, "sentences": len(texts),
            "exact": exact, "exact_pct": round(100 * exact / len(texts), 1),
            "char_pct": round(100 * chars_ok / max(chars_tot, 1), 1)}


def main():
    rows = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        for r in ex.map(measure, available_languages()):
            if r: rows.append(r)
    for code, meta in plain_latin_languages().items():
        rows.append({"code": code, "name": meta.get("name", ""), "sentences": None,
                     "exact": None, "exact_pct": 100.0, "char_pct": 100.0,
                     "note": "plain-Latin passthrough; apostrophes not restored"})
    rows.sort(key=lambda r: (-r["exact_pct"], r["code"]))
    out = REPO / "src" / "africa_g2p" / "data" / "reversibility.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    measured = [r for r in rows if r["sentences"]]
    print(f"measured {len(measured)} languages with charts, "
          f"plus {len(rows)-len(measured)} plain-Latin\n")
    print(f"{'code':<6}{'language':<26}{'exact':>7}{'chars':>8}")
    print("-" * 49)
    for r in rows:
        if r["sentences"]:
            print(f"{r['code']:<6}{r['name'][:24]:<26}{r['exact_pct']:>6.1f}%{r['char_pct']:>7.1f}%")
    print(f"\nwritten to {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
