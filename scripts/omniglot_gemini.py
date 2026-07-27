#!/usr/bin/env python3
"""Extract grapheme/IPA/romanisation data from Omniglot .xls charts using Gemini.

Omniglot charts (© Simon Ager) are hand-made spreadsheets with inconsistent layouts
(alphabet pairs, alphabet+example triplets, syllable grids, abjads). A fixed parser is
brittle, so we dump each sheet to a text grid and let Gemini read it into a fixed schema.

Usage:
    export GEMINI_API_KEY=...
    python scripts/omniglot_gemini.py --charts CHARTS_DIR --index omniglot_african.json \
        [--only akan yoruba] [--model gemini-3.6-flash] [--workers 4]

Writes one JSON per language to extraction/omniglot_raw/<iso>.json.
Downloads missing charts into CHARTS_DIR on demand.
"""
from __future__ import annotations

import argparse
import base64  # noqa: F401  (kept for parity with gemini_extract)
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "extraction" / "omniglot_raw"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
CHART_URL = "https://www.omniglot.com/charts/{slug}"

PROMPT = """You are reading an Omniglot writing-system chart (by Simon Ager) for an African language,
given below as a tab-separated grid of spreadsheet cells (row indices on the left). The chart may
contain MULTIPLE sheets marked "### SHEET: <name>" — typically an Alphabet sheet AND a
Pronunciation sheet (and for non-Latin scripts a Latin-alphabet or Syllabary sheet). USE ALL of
them together; the Pronunciation sheet often has fuller detail including multigraphs and IPA.
Layouts vary: some rows are LETTERS (often "A a" = uppercase+lowercase), some are IPA (usually in
[square brackets]), some are pronunciation-example syllables (e.g. "bi", "di") — and there are
section headers like "Tone marks" or "Nasal vowels".

Extract the writing system into ONE JSON object (no prose, no markdown) with this schema:

{
  "language": "<name>",
  "is_language_chart": true,
  "graphemes": [
    {"grapheme": "<one writing unit as actually written, lowercase>", "ipa": "<IPA>", "script": "latin|native"}
  ],
  "romanization": [ {"native": "<non-latin unit>", "latin": "<its latin form>"} ],
  "tones": { "<name>": "<mark/description>" },
  "diacritics": [ {"mark": "U+XXXX", "role": "<e.g. nasalization>", "ipa": "<IPA suffix>"} ],
  "notes": "<ambiguities/uncertainties>",
  "confidence": "high|medium|low"
}

Rules:
- A "grapheme" is ONE unit of the writing system: a single letter, a MULTIGRAPH (gb, kp, ny, sh,
  ch, gy, ...), or a syllable (for syllabaries). Take the lowercase form of "A a" -> "a".
- Put a valid IPA string in "ipa". If a cell shows alternatives like "[k͡p/p]", keep the first.
- IGNORE pronunciation-example syllables (the "bi","di" demonstration row) — the grapheme is the
  consonant/letter itself (b, d), and its IPA is the bracketed value.
- For non-Latin scripts, list each native unit as a grapheme (script:"native") AND add a
  "romanization" pair mapping it to its Latin form. Also include the Latin letters as graphemes
  (script:"latin") so both written forms work.
- Capture tone marks and nasal-vowel sets under "tones"/"diacritics".
- Never invent rows you cannot read; lower "confidence" and explain in "notes".
"""


# Sheets worth reading (alphabet + pronunciation + script/latin) vs noise to skip.
_SKIP_SHEET = ("punctuation", "number", "numeral", "phrase", "sample", "speaker",
               "obsolete", "text", "udhr")
_KEEP_HINT = ("alphabet", "pronunc", "syllab", "consonant", "vowel", "latin",
              "script", "abjad", "letter")


def _sheet_text(df) -> str:
    lines = []
    for r in range(df.shape[0]):
        cells = ["" if (v is None or str(v) == "nan") else str(v).strip() for v in df.iloc[r]]
        if any(cells):
            lines.append(f"row{r}\t" + "\t".join(cells))
    return "\n".join(lines)


def grid_to_text(path: str) -> str:
    """Concatenate the linguistically relevant sheets (Alphabet, Pronunciation, Latin…)."""
    import pandas as pd
    xl = pd.ExcelFile(path)
    names = xl.sheet_names
    keep = [n for n in names
            if not any(s in n.lower() for s in _SKIP_SHEET)
            and (any(h in n.lower() for h in _KEEP_HINT) or len(names) == 1)]
    if not keep:  # no obvious match — take non-noise sheets (e.g. "Yoruba (Nigeria)")
        keep = [n for n in names if not any(s in n.lower() for s in _SKIP_SHEET)]
    parts = []
    for n in keep:
        df = xl.parse(n, header=None, dtype=str)
        parts.append(f"### SHEET: {n}\n" + _sheet_text(df))
    return "\n\n".join(parts)


def _loads_lenient(txt: str) -> dict:
    """Parse model JSON, tolerating stray control chars or a truncated tail."""
    txt = "".join(c for c in txt if c >= " " or c in "\n\t")
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        pass
    # Truncated output: close the last complete top-level array element and braces.
    cut = txt.rfind("}")
    while cut > 0:
        candidate = txt[:cut + 1]
        for tail in ("]}", "}]}", "}"):
            try:
                return json.loads(candidate + tail)
            except json.JSONDecodeError:
                continue
        cut = txt.rfind("}", 0, cut)
    raise json.JSONDecodeError("unsalvageable", txt, 0)


def call_gemini(model: str, key: str, text: str, retries: int = 4) -> dict:
    body = {
        "contents": [{"parts": [{"text": PROMPT + "\n\nGRID:\n" + text}]}],
        "generationConfig": {"response_mime_type": "application/json", "temperature": 0,
                             "maxOutputTokens": 60000},
    }
    url = ENDPOINT.format(model=model, key=key)
    data = json.dumps(body).encode()
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                payload = json.load(resp)
            return _loads_lenient(payload["candidates"][0]["content"]["parts"][0]["text"])
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (429, 500, 503):
                time.sleep(2 ** attempt * 2); continue
            break
        except Exception as e:
            last = str(e); time.sleep(2 ** attempt)
    raise RuntimeError(last)


def ensure_chart(slug: str, charts_dir: Path) -> Path:
    p = charts_dir / slug
    if not p.exists() or p.stat().st_size == 0:
        req = urllib.request.Request(CHART_URL.format(slug=slug), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            p.write_bytes(resp.read())
    return p


def extract_one(entry: dict, charts_dir: Path, model: str, key: str, force: bool):
    iso = entry["iso"]
    out = RAW_DIR / f"{iso}.json"
    if out.exists() and not force:
        return iso, "skip"
    chart = ensure_chart(entry["slug"], charts_dir)
    result = call_gemini(model, key, grid_to_text(str(chart)))
    result.update({"iso": iso, "name": entry.get("name"),
                   "country": entry.get("country"), "family": entry.get("family"),
                   "slug": entry["slug"]})
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return iso, f"{len(result.get('graphemes', []))} graphemes, {result.get('confidence')}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--charts", required=True)
    ap.add_argument("--index", required=True, help="omniglot_african.json (slug/iso/name/...)")
    ap.add_argument("--only", nargs="*", help="restrict to these slugs or iso codes")
    ap.add_argument("--model", default="gemini-3.6-flash")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("Set GEMINI_API_KEY", file=sys.stderr); return 2
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    charts_dir = Path(args.charts); charts_dir.mkdir(parents=True, exist_ok=True)

    entries = json.loads(Path(args.index).read_text(encoding="utf-8"))
    # dedupe by iso (first chart wins)
    seen, uniq = set(), []
    for e in entries:
        if e["iso"] in seen:
            continue
        seen.add(e["iso"]); uniq.append(e)
    if args.only:
        want = set(args.only)
        uniq = [e for e in uniq if e["iso"] in want or e["slug"] in want
                or e["slug"].replace(".xls", "") in want]

    print(f"extracting {len(uniq)} charts with {args.model} ({args.workers} workers)")
    ok = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(extract_one, e, charts_dir, args.model, key, args.force): e for e in uniq}
        for fut in as_completed(futs):
            e = futs[fut]
            try:
                iso, msg = fut.result(); print(f"  {iso}: {msg}"); ok += 1
            except Exception as exc:
                print(f"  {e['iso']} ({e['slug']}): FAILED — {exc}", file=sys.stderr); fail += 1
    print(f"done: {ok} ok, {fail} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
