#!/usr/bin/env python3
"""Draft rule tables for languages that have corpus text but no chart.

Evidence in, table out: for each language the model is given the letter
frequencies, frequent digraphs and trigrams, and sample sentences actually
observed in that language's AfriSpeech/africa-corpus file -- never asked to
recall an orthography from memory. The result is validated against the same
corpus and rejected, with a specific reason fed back, until it passes.

Tables are written with ``"confidence": "llm-draft"`` and the model and corpus
recorded in ``"source"``. They are complete and well-formed; that is not the
same as every IPA value being correct.

Usage:
    GEMINI_API_KEY=... python scripts/draft_language_tables.py --list
    GEMINI_API_KEY=... python scripts/draft_language_tables.py --max-extended 8
    GEMINI_API_KEY=... python scripts/draft_language_tables.py --codes bwu sfw

Every check below was added after a real defect reached main. See PRs #13, #14
and #16.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LANG_DIR = REPO / "src" / "africa_g2p" / "languages"
CORPUS = "AfriSpeech/africa-corpus"

# Macrolanguage umbrellas the repo deliberately does not carry, because the
# actually-spoken varieties are covered instead. test_akan_macrolanguage_
# dropped_for_varieties enforces this for Akan.
SKIP_CODES = {"aka"}
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-pro-preview")

# values that must never be substituted into a transcription
WORDY = re.compile(r"[A-Za-z]{4,}")
LEAK = re.compile(r"(nasal|tone|accent|acute|grave|circumflex|tilde|macron|"
                  r"length|breve|caron|diaeresis|umlaut)", re.I)
# probed explicitly: relying on sample sentences to contain these is how the
# nasalisation bug in #13 reached main
PROBE = "ã ẽ ĩ õ ũ ɔ̃ ɛ̃ á à â ǎ ā é è ê í ì ó ò ú ù"


def hf_token() -> str:
    t = os.environ.get("HF_TOKEN")
    if t:
        return t
    return (Path.home() / ".cache/huggingface/token").read_text().strip()


def api_url() -> str:
    key = os.environ["GEMINI_API_KEY"]
    return (f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{MODEL}:generateContent?key={key}")


# --- corpus -------------------------------------------------------------------
def corpus_files() -> dict[str, tuple[str, str]]:
    """Map ISO code -> (pretty name, filename) for every corpus language."""
    req = urllib.request.Request(f"https://huggingface.co/api/datasets/{CORPUS}",
                                 headers={"Authorization": f"Bearer {hf_token()}"})
    out = {}
    for s in json.load(urllib.request.urlopen(req, timeout=120))["siblings"]:
        m = re.match(r"^(.*)_([a-z]{3})_v\d+\.csv$", s["rfilename"])
        if m and m.group(2) not in out:
            out[m.group(2)] = (m.group(1).replace("_", " "), s["rfilename"])
    return out


def corpus_evidence(fname: str, nbytes: int = 400_000) -> dict:
    url = (f"https://huggingface.co/datasets/{CORPUS}/resolve/main/"
           + urllib.parse.quote(fname))
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {hf_token()}",
                                               "Range": f"bytes=0-{nbytes}"})
    raw = urllib.request.urlopen(req, timeout=120).read().decode("utf-8", "replace")
    # columns: verse_key, version_id, local
    texts = [l.split(",", 2)[2].strip() for l in raw.splitlines()[1:] if l.count(",") >= 2]
    texts = [t for t in texts if t]
    chars = collections.Counter(c for t in texts for c in t.lower() if c.isalpha())
    joined = " ".join(texts[:4000]).lower()
    bi = collections.Counter(re.findall(r"(?=([^\W\d_]{2}))", joined))
    tri = collections.Counter(re.findall(r"(?=([^\W\d_]{3}))", joined))
    return {"chars": dict(chars.most_common()),
            "bigrams": [k for k, _ in bi.most_common(45)],
            "trigrams": [k for k, _ in tri.most_common(25)],
            "sample": texts[:6], "n": len(texts)}


PROMPT = """You are a descriptive linguist building a grapheme-to-phoneme table for
{name} (ISO 639-3: {code}), an African language.

The table maps ORTHOGRAPHIC graphemes to IPA and is consumed by a greedy
longest-match tokeniser, so multigraphs ("ny", "kp", "gb", "ch", "ts") must be
listed explicitly as their own keys.

EVIDENCE FROM A REAL CORPUS ({n} sentences).

Letters attested, by frequency:
{chars}

Frequent two-letter sequences (digraph candidates — include only those that are
genuinely single phonemes, not accidental sequences):
{bigrams}

Frequent three-letter sequences:
{trigrams}

Sample sentences:
{samples}

Return ONLY a JSON object, no markdown:

{{
  "code": "{code}",
  "name": "{name}",
  "country": "",
  "family": "<language family>",
  "scripts": {{"native": [], "latin": [<every grapheme, ordered>]}},
  "graphemes": {{"<grapheme>": "<IPA>", ...}},
  "romanization": {{}},
  "diacritics": {{"<combining mark>": "<IPA realisation>", ...}},
  "tones": {{"<tone name>": "<how it is written>", ...}},
  "notes": "<one or two sentences; flag anything uncertain>",
  "alphabet": [<every grapheme, ordered>],
  "examples": []
}}

HARD REQUIREMENTS — a table breaking any of these is rejected:

1. Every attested letter must be reachable: present as a grapheme key, or as a
   base letter whose combining mark is handled in "diacritics".

2. "diacritics" VALUES ARE SUBSTITUTED INTO OUTPUT. They must be IPA symbols or
   combining marks, NEVER English words. Correct:
     {{"\\u0303": "\\u0303"}}  nasalisation
     {{"\\u0301": "\\u02e5"}}  high tone
     {{"\\u0300": "\\u02e9"}}  low tone
   FORBIDDEN: {{"\\u0301": "high tone"}} — that transcribes a word as
   "ɔhightonesu".

3. If you map the combining tilde in "diacritics", DO NOT also list precomposed
   nasal vowels (ã ẽ ĩ õ ũ) as graphemes. The engine decomposes first, so those
   keys can never match. The tilde in "diacritics" is preferred.

4. "tones" is documentation only, never substituted: key it by tone NAME.

5. West African conventions: <ɛ>=ɛ, <ɔ>=ɔ, <ŋ>=ŋ, <ɩ>=ɪ, <ʋ>=ʊ, <ǝ>=ə, <ƒ>=f,
   <y>=j, <kp>=k͡p, <gb>=ɡ͡b, <ny>=ɲ, <ch>=t͡ʃ, <j>=d͡ʒ.

6. The voiced velar stop is U+0261 "\\u0261", NEVER ASCII "g" — anywhere a value
   contains that sound. A value containing ASCII "g" is rejected.

7. No empty grapheme values.
"""


def ask(prompt: str, retries: int = 3) -> str:
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.2,
                                            "maxOutputTokens": 24576}}).encode()
    for a in range(retries):
        try:
            req = urllib.request.Request(api_url(), data=body,
                                         headers={"Content-Type": "application/json"})
            d = json.load(urllib.request.urlopen(req, timeout=300))
            return d["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            if a == retries - 1:
                raise
            time.sleep(4 * (a + 1))
    raise RuntimeError("unreachable")


def parse(txt: str) -> dict:
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise ValueError("no JSON in response")
    return json.loads(m.group(0))


def check(tbl: dict, info: dict) -> list[str]:
    """Concrete problems with the table; empty means acceptable."""
    problems: list[str] = []
    gr = tbl.get("graphemes") or {}
    dia = tbl.get("diacritics") or {}
    if not gr:
        return ["graphemes is empty"]

    for field, typ in (("graphemes", dict), ("diacritics", dict), ("tones", dict),
                       ("romanization", dict), ("alphabet", list),
                       ("examples", list), ("scripts", dict)):
        if field in tbl and not isinstance(tbl[field], typ):
            problems.append(f"{field} must be a {typ.__name__}, got "
                            f"{type(tbl[field]).__name__}")
    for k, v in (tbl.get("scripts") or {}).items():
        if not isinstance(v, list):
            problems.append(f"scripts[{k!r}] must be a list")

    for k, v in gr.items():
        if not str(v).strip():
            problems.append(f"grapheme {k!r} has an empty value")
        if "g" in str(v):
            problems.append(f"grapheme {k!r} = {v!r} uses ASCII 'g'; IPA requires "
                            f"U+0261 'ɡ'")
    for field in ("diacritics", "romanization"):
        for k, v in (tbl.get(field) or {}).items():
            if "g" in str(v):
                problems.append(f"{field}[{k!r}] = {v!r} uses ASCII 'g'; "
                                f"IPA requires U+0261")
    for k, v in dia.items():
        if WORDY.search(str(v)):
            problems.append(f"diacritics[{k!r}] = {v!r} is prose; it is substituted "
                            f"into output and must be an IPA symbol or mark")

    for k in gr:
        d = unicodedata.normalize("NFD", k)
        base_present = d[0].lower() in {x.lower() for x in gr}
        if len(d) >= 2 and all(m in dia for m in d[1:]) and base_present:
            problems.append(f"grapheme {k!r} is precomposed and its mark is already "
                            f"in diacritics; it can never match — remove it")

    keys = {k.lower() for k in gr}
    for c in info["chars"]:
        if c in keys:
            continue
        # A letter may carry several stacked marks -- ṹ is u + tilde + acute.
        # It is reachable when the base is a grapheme and *every* mark is in
        # diacritics, however many there are. Assuming one mark is how the
        # tranche-3 failures (ṹ, ń, ü) were produced.
        d = unicodedata.normalize("NFD", c)
        base, marks = d[0], d[1:]
        if marks and base in keys and all(m in dia for m in marks):
            continue
        problems.append(f"attested letter {c!r} is not reachable "
                        f"(base {base!r}, marks {[hex(ord(m)) for m in marks]})")
    return problems


def runtime_check(code: str, info: dict) -> list[str]:
    """Load the written table and convert probes; catch prose leaking into output."""
    sys.path.insert(0, str(REPO / "src"))
    for m in [m for m in sys.modules if m.startswith("africa_g2p")]:
        del sys.modules[m]
    from africa_g2p import UNIVERSAL, GraphemeConverter
    from africa_g2p.g2p import G2P
    text = PROBE + " " + " ".join(info["sample"][:4])
    try:
        out = GraphemeConverter(code, UNIVERSAL).convert(text)
        G2P(code, output="ipa").phonemes("test")
    except Exception as exc:
        return [f"runtime failure: {type(exc).__name__}: {exc}"]
    leaked = {m.group(0).lower() for m in LEAK.finditer(out)}
    leaked -= {w.lower() for w in LEAK.findall(text)}
    return [f"output contains {sorted(leaked)} — a diacritic value is leaking prose"] \
        if leaked else []


def build(code: str, name: str, fname: str, attempts: int = 3):
    try:
        info = corpus_evidence(fname)
    except Exception as exc:
        return code, None, [f"corpus fetch failed: {type(exc).__name__}"]
    if not info["chars"]:
        return code, None, ["corpus produced no text"]

    base = PROMPT.format(
        name=name, code=code, n=info["n"],
        chars=", ".join(f"{c} ({n})" for c, n in list(info["chars"].items())[:40]),
        bigrams=", ".join(info["bigrams"][:40]),
        trigrams=", ".join(info["trigrams"][:20]),
        samples="\n".join("  " + s[:150] for s in info["sample"][:5]))

    prompt, last = base, ["no attempt made"]
    for _ in range(attempts):
        try:
            tbl = parse(ask(prompt))
        except Exception as exc:
            last = [f"generation failed: {type(exc).__name__}"]
            continue
        tbl["source"] = (f"Drafted by {MODEL} from the {CORPUS} {code} corpus "
                         f"({info['n']} sentences); not reviewed by a speaker.")
        tbl["confidence"] = "llm-draft"
        tbl["examples"] = []
        probs = check(tbl, info)
        if not probs:
            (LANG_DIR / f"{code}.json").write_text(
                json.dumps(tbl, ensure_ascii=False, indent=2), encoding="utf-8")
            probs = runtime_check(code, info)
            if not probs:
                return code, tbl, []
            (LANG_DIR / f"{code}.json").unlink(missing_ok=True)
        last = probs
        prompt = (base + "\n\nYour previous attempt was REJECTED. Fix every one:\n"
                  + "\n".join(f"- {p}" for p in probs[:12]))
    return code, None, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", nargs="*", help="specific ISO codes")
    ap.add_argument("--max-extended", type=int, default=3,
                    help="only languages with at most N non-ASCII letters")
    ap.add_argument("--min-extended", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--list", action="store_true", help="show candidates and exit")
    args = ap.parse_args()

    sys.path.insert(0, str(REPO / "src"))
    from africa_g2p import available_languages
    from africa_g2p.convert import plain_latin_languages
    covered = set(available_languages()) | set(plain_latin_languages())

    files = corpus_files()
    todo = []
    if args.codes:
        todo = [(c, *files[c]) for c in args.codes
                if c in files and c not in SKIP_CODES]
    else:
        print(f"surveying {len(files) - len(covered & set(files))} uncovered "
              f"languages...", flush=True)
        for code, (name, fname) in sorted(files.items()):
            if code in covered or code in SKIP_CODES:
                continue
            try:
                ev = corpus_evidence(fname, 120_000)
            except Exception:
                continue
            n = len([k for k in ev["chars"] if not k.isascii()])
            if args.min_extended <= n <= args.max_extended:
                todo.append((code, name, fname))

    print(f"{len(todo)} languages to draft", flush=True)
    if args.list:
        for c, n, _ in todo:
            print(f"  {c}  {n}")
        return

    ok, failed = [], {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for code, tbl, probs in ex.map(lambda t: build(*t), todo):
            if tbl:
                ok.append(code)
                print(f"  {code:<5} OK   {len(tbl['graphemes'])} graphemes", flush=True)
            else:
                failed[code] = probs
                print(f"  {code:<5} FAIL {probs[0][:70] if probs else ''}", flush=True)
    print(f"\nwritten {len(ok)}, failed {len(failed)}")
    if failed:
        print("failed:", " ".join(failed))
    print("\nNow run the test suite — it has caught defects this script did not:")
    print("    python -m pytest tests/ -q")


if __name__ == "__main__":
    main()
