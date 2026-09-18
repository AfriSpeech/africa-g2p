#!/usr/bin/env python3
"""Score each language's proxy alphabet: does orthography -> proxy -> orthography
return the original?

Measured on real corpus text rather than invented examples, and reported per
language rather than as an average, because a mean hides the languages a
consumer actually cares about.

    python scripts/measure_proxy.py
"""

from __future__ import annotations

import collections
import concurrent.futures as cf
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from africa_g2p import GraphemeConverter, PROXY                    # noqa: E402
from africa_g2p.normalizer import normalize_text                   # noqa: E402

CORPUS = "AfriSpeech/africa-corpus"
OUT = REPO / "src/africa_g2p/data/proxy_fidelity.json"
N = 60


def hf_token() -> str:
    import os
    return (os.environ.get("HF_TOKEN")
            or (Path.home() / ".cache/huggingface/token").read_text().strip())


def corpus_files() -> dict:
    req = urllib.request.Request(f"https://huggingface.co/api/datasets/{CORPUS}",
                                 headers={"Authorization": f"Bearer {hf_token()}"})
    out = {}
    for s in json.load(urllib.request.urlopen(req, timeout=300))["siblings"]:
        m = re.match(r"^(.*)_([a-z]{3})_v\d+\.csv$", s["rfilename"])
        if m:
            out.setdefault(m.group(2), (m.group(1).replace("_", " "), s["rfilename"]))
    return out


def score(code: str, name: str, fname: str) -> dict | None:
    try:
        url = (f"https://huggingface.co/datasets/{CORPUS}/resolve/main/"
               + urllib.parse.quote(fname))
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {hf_token()}",
                                                   "Range": "bytes=0-300000"})
        raw = urllib.request.urlopen(req, timeout=120).read().decode("utf-8", "replace")
        texts = [l.split(",", 2)[2].strip() for l in raw.splitlines()[1:]
                 if l.count(",") >= 2]
        texts = [t for t in texts if t][:N]
        if not texts:
            return None
        fwd = GraphemeConverter(code, PROXY)
        back = GraphemeConverter(PROXY, code)
    except Exception:
        return None

    exact = 0
    kept = total = 0
    non_az = 0
    for t in texts:
        want = normalize_text(t)
        try:
            mid = fwd.convert(t)
            got = back.convert(mid)
        except Exception:
            continue
        if got == want:
            exact += 1
        for a, b in zip(want, got):
            total += 1
            kept += (a == b)
        total += abs(len(want) - len(got))
        non_az += sum(1 for c in mid if c.isalpha() and not ("a" <= c <= "z"))
    if not total:
        return None
    return {"code": code, "name": name, "sentences": len(texts), "exact": exact,
            "exact_pct": round(100 * exact / len(texts), 1),
            "char_pct": round(100 * kept / total, 1),
            "non_az_in_proxy": non_az}


def main():
    files = corpus_files()
    rows = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(score, c, n, f) for c, (n, f) in sorted(files.items())]
        for fu in cf.as_completed(futs):
            r = fu.result()
            if r:
                rows.append(r)
    rows.sort(key=lambda r: (-r["exact_pct"], -r["char_pct"], r["code"]))
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    n = len(rows)
    b = collections.Counter()
    for r in rows:
        e = r["exact_pct"]
        b["100%" if e >= 99.999 else "95-99%" if e >= 95 else
          "75-94%" if e >= 75 else "50-74%" if e >= 50 else "<50%"] += 1
    print(f"measured {n} languages on real corpus text, {N} sentences each\n")
    for k in ("100%", "95-99%", "75-94%", "50-74%", "<50%"):
        print(f"   {k:<8}{b[k]:>5}  ({100*b[k]/n:.0f}%)")
    print(f"\n   mean character fidelity : {sum(r['char_pct'] for r in rows)/n:.1f}%")
    print(f"   >=99% of characters     : {sum(1 for r in rows if r['char_pct']>=99)}")
    print(f"   proxy text not plain a-z: {sum(1 for r in rows if r['non_az_in_proxy'])}")
    gh = ["twi", "fat", "ewe", "dag", "gaa", "nzi", "bwu", "kus", "xsm", "dga",
          "gjn", "akp", "ada"]
    print("\n   Ghanaian:")
    for c in gh:
        r = next((x for x in rows if x["code"] == c), None)
        if r:
            print(f"      {c:<5}{r['exact_pct']:>6.1f}%   chars {r['char_pct']:>5.1f}%")
    print("\n   worst 10:", " ".join(r["code"] for r in rows[-10:]))
    print(f"\nwritten to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
