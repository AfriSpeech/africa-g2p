#!/usr/bin/env python3
"""Vision-extract language pages from the rendered PNGs using the Gemini API.

Reads the extraction contract (scripts/EXTRACTION.md), sends each page image to
Gemini, and writes one JSON object per page to extraction/raw/p-NNN.json — the same
format scripts/build_rules.py consumes.

Setup:
    export GEMINI_API_KEY=...            # never commit this
Usage:
    python scripts/gemini_extract.py                     # all pages, skip done
    python scripts/gemini_extract.py --pages 40 41 42    # specific pages
    python scripts/gemini_extract.py --pages 40-60        # a range
    python scripts/gemini_extract.py --model gemini-2.5-pro --force --workers 6

Uses only the standard library (urllib) — no extra dependencies.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT / "extraction" / "pages"
RAW_DIR = ROOT / "extraction" / "raw"
CONTRACT = (ROOT / "scripts" / "EXTRACTION.md").read_text(encoding="utf-8")

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

PROMPT = f"""You are extracting phoneme/orthography data from a scanned page of Rhonda L. Hartell's \
*Alphabets of Africa* (UNESCO, 1993), to build a grapheme-to-phoneme (G2P) dataset for African languages.

Follow this contract EXACTLY and output ONLY a single JSON object (no markdown, no prose) matching the schema:

{CONTRACT}

Reminders:
- The left table is `/phoneme/ -> orthographic symbol`. The orthographic symbol is the "grapheme";
  put a valid IPA rendering of the phoneme in "phoneme". Convert Hartell notations (/ty/, /dy/, /Ṽ/,
  b-with-hook, dotted/underdotted letters, small-caps) to proper IPA and explain ambiguous choices in "notes".
- Capture ALL multigraphs exactly (kp, gb, ny, ŋ, gh, sh, ch, digraphs, underdot variants, etc.).
- Capture tones/nasalization/length as "diacritics" entries and/or the "tones" object.
- Capture the ALPHABET row and the EXAMPLES (word + gloss).
- If the page has no phoneme table (cover, TOC, divider, continuation, notes), set "is_language_page": false.
- Never invent unreadable cells; lower "confidence" and add a "notes" entry instead.
- Set the "page" field to the page number you are told below."""


def page_num(path: Path) -> int:
    m = re.search(r"(\d+)", path.stem)
    return int(m.group(1)) if m else -1


def parse_pages(spec: list[str]) -> set[int]:
    out: set[int] = set()
    for s in spec:
        if "-" in s:
            a, b = s.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(s))
    return out


def call_gemini(model: str, key: str, img_b64: str, page: int, retries: int = 4) -> dict:
    body = {
        "contents": [{
            "parts": [
                {"text": PROMPT + f"\n\nThis image is page {page}."},
                {"inline_data": {"mime_type": "image/png", "data": img_b64}},
            ]
        }],
        "generationConfig": {"response_mime_type": "application/json", "temperature": 0},
    }
    url = ENDPOINT.format(model=model, key=key)
    data = json.dumps(body).encode()
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                payload = json.load(resp)
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"
            if e.code in (429, 500, 503):
                time.sleep(2 ** attempt * 2)
                continue
            break
        except Exception as e:  # network hiccup, JSON parse, etc.
            last_err = str(e)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"page {page}: {last_err}")


def extract_one(path: Path, model: str, key: str, force: bool) -> tuple[int, str]:
    page = page_num(path)
    out = RAW_DIR / f"p-{page:03d}.json"
    if out.exists() and not force:
        return page, "skip (exists)"
    img_b64 = base64.b64encode(path.read_bytes()).decode()
    result = call_gemini(model, key, img_b64, page)
    result.setdefault("page", page)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lang = result.get("language", "?") if result.get("is_language_page", True) else "(not a language page)"
    conf = result.get("confidence", "")
    ng = len(result.get("graphemes", []))
    return page, f"{lang} [{ng} graphemes, {conf}]"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pages", nargs="*", help="page numbers or ranges (e.g. 40 41 50-60); default all")
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("Set GEMINI_API_KEY in the environment.", file=sys.stderr)
        return 2

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    all_pages = sorted(PAGES_DIR.glob("p*.png"), key=page_num)
    if args.pages:
        want = parse_pages(args.pages)
        all_pages = [p for p in all_pages if page_num(p) in want]
    if not all_pages:
        print("No matching page images found.", file=sys.stderr)
        return 1

    print(f"extracting {len(all_pages)} pages with {args.model} ({args.workers} workers)...")
    ok = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(extract_one, p, args.model, key, args.force): p for p in all_pages}
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                page, msg = fut.result()
                print(f"  p{page:03d}: {msg}")
                ok += 1
            except Exception as e:
                print(f"  p{page_num(p):03d}: FAILED — {e}", file=sys.stderr)
                fail += 1
    print(f"done: {ok} ok, {fail} failed")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
