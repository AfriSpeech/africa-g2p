#!/usr/bin/env python3
"""Generate the README language showcase from real corpus samples.

For every language that has both a rule file and a match in the AfriSpeech
africa-corpus dataset, fetch a few real sentences, phonemise them, keep the
best-covered short ones, and emit a collapsible Markdown block per language.

Requires the africa-corpus-builder on PYTHONPATH and `huggingface_hub` installed:
    export PYTHONPATH=/path/to/africa-corpus-builder
    python scripts/make_showcase.py > docs/SHOWCASE.md

Writes docs/showcase.json (data) and prints the Markdown to stdout.
"""
from __future__ import annotations

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

import afriso  # canonical African language name <-> ISO 639-3 resolver

MAX_LEN = 120         # keep sample sentences short enough to read
MIN_COV = 0.90        # a language is shown if its best sample covers this well
PER_LANG = 2          # samples shown per language
FETCH = 20            # candidates to fetch before picking the best-covered


def to_iso(text: str):
    """Resolve a language name or code to canonical ISO 639-3 via afriso, else None."""
    for cand in (text, re.split(r"[(/]", text)[0].strip()):
        try:
            return afriso.to_iso(cand)
        except Exception:
            continue
    return None


def coverage(g2p: G2P, text: str) -> float:
    marked = g2p.convert(text)  # g2p built with unknown="mark"
    letters = sum(c.isalpha() for c in text)
    return 1.0 - (marked.count("�") / letters) if letters else 0.0


def build_match_map(versions_csv: Path) -> dict:
    """Map each rule-file code -> (name, corpus_code), joined on canonical ISO 639-3."""
    reg = registry()
    # corpus canonical ISO -> corpus code
    corpus = {}
    with versions_csv.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("has_text") != "true":
                continue
            iso = to_iso(r["lang_code"]) or to_iso(r["lang_name"])
            if iso:
                corpus.setdefault(iso, r["lang_code"])
    matches = {}
    for code in available_languages():
        name = reg.get(code, {}).get("name", "")
        iso = to_iso(name)
        cc = corpus.get(iso) if iso else None
        if cc:
            matches[code] = (name, cc)
    return matches


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True, help="youversion_africa_versions.csv path")
    args = ap.parse_args()

    import africa_corpus as ac

    matches = build_match_map(Path(args.versions))
    reg = registry()
    out_data = []

    # Group my rule-file codes by the corpus code they matched, so a corpus text is
    # fetched once and phonemised by the best-fitting variant (e.g. hau-nigeria, not hau-niger).
    by_cc: dict[str, list[str]] = {}
    for code, (_, cc) in matches.items():
        by_cc.setdefault(cc, []).append(code)

    for cc, codes in sorted(by_cc.items()):
        try:
            cands = [s.strip() for s in ac.monolingual(cc, limit=FETCH, sample=True, seed=7)]
        except Exception as e:
            print(f"<!-- {cc}: fetch failed: {e} -->", file=sys.stderr)
            continue
        cands = [s for s in cands if 8 <= len(s) <= MAX_LEN]
        if not cands:
            continue
        # pick the rule-file variant with the best mean coverage on these sentences
        best_code, best_cov = None, -1.0
        for code in codes:
            gm = G2P(code, unknown="mark")
            m = sum(coverage(gm, s) for s in cands) / len(cands)
            if m > best_cov:
                best_code, best_cov = code, m
        g_mark = G2P(best_code, output="grapheme", unknown="mark")
        g_native = G2P(best_code, output="grapheme")
        g_ipa = G2P(best_code, output="ipa")
        scored = sorted(((coverage(g_mark, s), s) for s in cands), reverse=True)
        picks = [s for cov, s in scored if cov >= MIN_COV][:PER_LANG]
        if not picks:
            print(f"<!-- skip {best_code}: best coverage {best_cov*100:.0f}% -->", file=sys.stderr)
            continue
        out_data.append({
            "code": best_code,
            "name": matches[best_code][0],
            "country": reg.get(best_code, {}).get("country"),
            "samples": [{
                "text": s,
                "native": g_native.convert(s, sep=" "),
                "ipa": g_ipa.convert(s, sep=" "),
            } for s in picks],
        })
        print(f"<!-- ok {best_code} ({matches[best_code][0]}) {len(picks)} samples -->", file=sys.stderr)

    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "showcase.json").write_text(
        json.dumps(out_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- emit markdown ----
    print(f"Real sentences from the "
          f"[africa-corpus](https://github.com/AfriSpeech/africa-corpus-builder) dataset, "
          f"segmented by africa-g2p into native-orthography phonemes (default) with the IPA "
          f"shown for reference. {len(out_data)} languages.\n")
    for e in sorted(out_data, key=lambda x: x["name"].lower()):
        loc = f" · {e['country']}" if e.get("country") else ""
        print(f"<details>\n<summary><b>{e['name']}</b> (<code>{e['code']}</code>{loc})</summary>\n")
        for s in e["samples"]:
            print(f"> **Text:** {s['text']}  ")
            print(f"> **Phonemes:** `{s['native']}`  ")
            print(f"> **IPA:** `{s['ipa']}`\n")
        print("</details>\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
