#!/usr/bin/env python3
"""Validate phonemisation on real corpus text for every supported language.

For each language that has both a rule file and a match in the AfriSpeech africa-corpus
(joined on canonical ISO 639-3 via afriso), fetch real sentences and measure how much of
the text the engine actually maps — i.e. the fraction of alphabetic characters consumed by
a known grapheme unit (the rest fall through as unknown). This tells us whether a language
we *claim* to support actually phonemises real text, not just that its file loads.

Usage:
    export PYTHONPATH=/path/to/africa-corpus-builder
    python scripts/corpus_qa.py --versions youversion_africa_versions.csv [--limit 15]

Writes docs/coverage.json and prints a bucketed summary + the languages needing review.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata as U
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from africa_g2p import G2P, available_languages  # noqa: E402
from africa_g2p.loader import registry  # noqa: E402
import afriso  # noqa: E402


def to_iso(text: str):
    for cand in (text or "", re.split(r"[(/]", text or "")[0].strip()):
        try:
            return afriso.to_iso(cand)
        except Exception:
            continue
    return None


def coverage(g2p: G2P, text: str) -> float:
    letters = sum(c.isalpha() for c in text)
    if not letters:
        return 1.0
    return 1.0 - g2p.convert(text).count("�") / letters


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--versions", required=True)
    ap.add_argument("--limit", type=int, default=15)
    args = ap.parse_args()

    import africa_corpus as ac

    # corpus canonical ISO -> corpus code
    corpus = {}
    with open(args.versions, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("has_text") != "true":
                continue
            iso = to_iso(r["lang_code"]) or to_iso(r["lang_name"])
            if iso:
                corpus.setdefault(iso, r["lang_code"])

    reg = registry()
    # our languages -> canonical ISO -> corpus code
    targets = {}
    for code in available_languages():
        iso = reg.get(code, {}).get("iso639_3") or to_iso(reg.get(code, {}).get("name", ""))
        cc = corpus.get(iso) if iso else None
        if cc:
            targets.setdefault(cc, code)  # one language per corpus file

    report = []
    for cc, code in sorted(targets.items(), key=lambda kv: kv[1]):
        try:
            sents = [s.strip() for s in ac.monolingual(cc, limit=args.limit, sample=True, seed=7)]
        except Exception as e:
            report.append({"code": code, "corpus": cc, "status": "fetch_failed", "note": str(e)[:80]})
            continue
        sents = [s for s in sents if 8 <= len(s) <= 200]
        if not sents:
            report.append({"code": code, "corpus": cc, "status": "no_text"})
            continue
        gm = G2P(code, unknown="mark")
        covs = [coverage(gm, s) for s in sents]
        mean = sum(covs) / len(covs)
        report.append({"code": code, "corpus": cc, "name": reg.get(code, {}).get("name"),
                       "coverage": round(mean, 3), "n": len(sents),
                       "example": {"text": sents[0], "phonemes": G2P(code).convert(sents[0], sep=" ")}})
        print(f"  {code:14s} {mean*100:5.1f}%  {reg.get(code, {}).get('name','')}")

    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "coverage.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    scored = [r for r in report if "coverage" in r]
    def pct(lo, hi): return sum(1 for r in scored if lo <= r["coverage"] < hi)
    print("\n=== coverage summary (languages tested on real corpus text) ===")
    print(f"  tested:            {len(scored)}")
    print(f"  excellent >=95%:   {pct(0.95, 1.01)}")
    print(f"  good 85-95%:       {pct(0.85, 0.95)}")
    print(f"  partial 60-85%:    {pct(0.60, 0.85)}")
    print(f"  poor <60%:         {pct(0.0, 0.60)}")
    print(f"  fetch failed/none: {len(report) - len(scored)}")
    print(f"  (no corpus match): {len(available_languages()) - len(targets)} languages untested")
    low = sorted((r for r in scored if r["coverage"] < 0.85), key=lambda r: r["coverage"])
    if low:
        print("\nlanguages below 85% (review):")
        for r in low:
            print(f"  {r['code']:14s} {r['coverage']*100:5.1f}%  {r.get('name','')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
