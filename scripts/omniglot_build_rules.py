#!/usr/bin/env python3
"""Compile Gemini-extracted Omniglot data (extraction/omniglot_raw/*.json) into rule files.

Adds languages that are NOT already covered (from Hartell) — existing rule files are kept
so hand-fixed/tested languages are never regressed. Rebuilds the registry from all rule
files afterwards. Run scripts/enrich_registry.py next to re-add afriso metadata.

Usage:
    python scripts/omniglot_build_rules.py [--overwrite-omniglot]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from build_rules import norm_ipa, _reg  # reuse helpers
import afriso


def _canon_iso(name: str):
    for cand in (name or "", re.split(r"[(/]", name or "")[0].strip()):
        try:
            return afriso.to_iso(cand)
        except Exception:
            continue
    return None

RAW_DIR = ROOT / "extraction" / "omniglot_raw"
LANG_DIR = ROOT / "src" / "africa_g2p" / "languages"
REGISTRY = ROOT / "src" / "africa_g2p" / "data" / "registry.json"


def to_rule(raw: dict) -> dict | None:
    if not raw.get("is_language_chart", True):
        return None
    graphemes = {}
    for row in raw.get("graphemes", []):
        g = (row.get("grapheme") or "").strip()
        ipa = norm_ipa((row.get("ipa") or "").strip())
        if g and ipa and g not in graphemes:
            graphemes[g] = ipa
    if not graphemes:
        return None

    romanization = {}
    for r in raw.get("romanization", []):
        nat, lat = (r.get("native") or "").strip(), (r.get("latin") or "").strip()
        if nat and lat and nat not in romanization:
            romanization[nat] = lat

    diacritics = {}
    for d in raw.get("diacritics", []) or []:
        mark = d.get("mark", "")
        if isinstance(mark, str) and mark.startswith("U+"):
            try:
                mark = chr(int(mark[2:], 16))
            except ValueError:
                continue
        if mark and d.get("ipa"):
            diacritics[mark] = d["ipa"]

    latin_alpha = sorted({row["grapheme"] for row in raw.get("graphemes", [])
                          if row.get("grapheme") and row.get("script") != "native"})
    return {
        "code": raw["iso"],
        "name": raw.get("name", raw["iso"]),
        "country": raw.get("country"),
        "family": raw.get("family"),
        "source": f"Omniglot chart ({raw.get('slug')}), © Simon Ager, https://omniglot.com",
        "confidence": "omniglot",
        "scripts": {
            "native": sorted({r["grapheme"] for r in raw.get("graphemes", []) if r.get("script") == "native"}),
            "latin": latin_alpha,
        },
        "graphemes": graphemes,
        "romanization": romanization,
        "diacritics": diacritics,
        "tones": raw.get("tones", {}),
        "notes": raw.get("notes", ""),
        "alphabet": latin_alpha,
        "examples": [],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep-pdf-overlaps", action="store_true",
                    help="do NOT replace existing PDF languages that omniglot also covers")
    args = ap.parse_args()

    # Map each existing rule file to its canonical ISO, and note hand-verified ones.
    existing_by_iso: dict[str, list[Path]] = {}
    protected: set[str] = set()  # filenames we never delete/overwrite
    for p in LANG_DIR.glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("confidence") == "hand-verified":
            protected.add(p.name)
        iso = d.get("iso639_3") or _canon_iso(d.get("name", ""))
        if iso:
            existing_by_iso.setdefault(iso, []).append(p)

    added = replaced = skipped = 0
    for rp in sorted(RAW_DIR.glob("*.json")):
        raw = json.loads(rp.read_text(encoding="utf-8"))
        rule = to_rule(raw)
        if rule is None:
            skipped += 1
            continue
        iso = rule["code"]
        # Prefer omniglot: remove PDF versions of this language (any code) unless protected.
        if not args.keep_pdf_overlaps:
            for old in existing_by_iso.get(iso, []):
                if old.name not in protected and old.name != f"{iso}.json" and old.exists():
                    old.unlink()
                    replaced += 1
        out = LANG_DIR / f"{iso}.json"
        if out.name in protected:
            skipped += 1
            continue
        if out.exists() and args.keep_pdf_overlaps:
            skipped += 1
            continue
        was = out.exists()
        out.write_text(json.dumps(rule, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        added += 0 if was else 1
        replaced += 1 if was else 0

    registry = sorted((_reg(json.loads(p.read_text(encoding="utf-8")))
                       for p in LANG_DIR.glob("*.json")), key=lambda e: e["code"])
    REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"added {added} new, replaced {replaced} PDF/omniglot, skipped {skipped}; "
          f"registry now has {len(registry)} languages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
