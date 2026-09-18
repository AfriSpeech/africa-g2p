#!/usr/bin/env python3
"""Ask a model how to write letters that no rule table covers.

The fallback table is built by vote: a letter a language's own table omits is
written the way the most other tables write it. That only works for letters some
table lists. A handful appear in real corpus text and in no table at all -- the
Vai syllable ꘋ, the hooked letters ƃ ƌ ƴ -- so there is nothing to vote on, and
they survive into universal output unconverted.

This asks for those, one batch at a time, with the languages each letter was
actually seen in. The answer is validated before it is used: a spelling must be
plain a-z (the universal orthography has nothing else), must be short, and must
not silently become empty.

    GEMINI_API_KEY=... python scripts/fill_universal_fallback.py --dry-run
    GEMINI_API_KEY=... python scripts/fill_universal_fallback.py
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
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from africa_g2p import GraphemeConverter, UNIVERSAL          # noqa: E402
from africa_g2p.convert import universal_fallback            # noqa: E402

CORPUS = "AfriSpeech/africa-corpus"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-pro-preview")
FALLBACK = REPO / "src/africa_g2p/data/universal_fallback.json"


def hf_token() -> str:
    return (os.environ.get("HF_TOKEN")
            or (Path.home() / ".cache/huggingface/token").read_text().strip())


def corpus_files() -> dict:
    req = urllib.request.Request(f"https://huggingface.co/api/datasets/{CORPUS}",
                                 headers={"Authorization": f"Bearer {hf_token()}"})
    out = collections.defaultdict(list)
    for s in json.load(urllib.request.urlopen(req, timeout=300))["siblings"]:
        m = re.match(r"^(.*)_([a-z]{3})_v\d+\.csv$", s["rfilename"])
        if m:
            out[m.group(2)].append((m.group(1).replace("_", " "), s["rfilename"]))
    return out


def survey(files: dict, limit: int | None = None) -> dict:
    """Letters that reach universal output unconverted, and where they came from."""
    seen: dict = collections.defaultdict(lambda: {"count": 0, "langs": collections.Counter(),
                                                  "words": []})
    codes = sorted(files)[:limit] if limit else sorted(files)
    for code in codes:
        for name, fn in files[code]:
            try:
                url = (f"https://huggingface.co/datasets/{CORPUS}/resolve/main/"
                       + urllib.parse.quote(fn))
                req = urllib.request.Request(
                    url, headers={"Authorization": f"Bearer {hf_token()}",
                                  "Range": "bytes=0-60000"})
                raw = urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace")
                texts = [l.split(",", 2)[2].strip() for l in raw.splitlines()[1:]
                         if l.count(",") >= 2][:20]
                if not texts:
                    continue
                conv = GraphemeConverter(code, UNIVERSAL)
            except Exception:
                continue
            for t in texts:
                try:
                    out = conv.convert(t)
                except Exception:
                    continue
                for ch in out:
                    if not ch.isalpha() or ("a" <= ch <= "z"):
                        continue
                    if universal_fallback(ch) is not None:
                        continue          # already covered by vote
                    e = seen[ch]
                    e["count"] += 1
                    e["langs"][f"{name} ({code})"] += 1
                    if len(e["words"]) < 4:
                        for w in re.findall(r"[^\W\d_]*" + re.escape(ch) + r"[^\W\d_]*", t):
                            if w and w not in e["words"]:
                                e["words"].append(w)
                                break
    return seen


PROMPT = """You are completing a transliteration table for African language text.

Each letter below appears in real text of the languages named, and no rule table
in the package covers it, so it currently survives untransliterated.

Give, for each, the spelling to use in a PLAIN a-z Latin orthography: the way
that letter's sound is ordinarily written with ASCII letters only.

{letters}

Return ONLY JSON, no prose:

{{"letters": [{{"char": "<the letter>",
               "spell": "<plain a-z spelling, or empty string>",
               "ipa": "<its IPA value>",
               "why": "<one short sentence>"}}]}}

Rules:
  - "spell" must contain only a-z, nothing else: no accents, no IPA symbols, no
    capitals. Write ɔ as "o", ʃ as "sh", ŋ as "ng".
  - Use the empty string ONLY for something that marks length, tone, stress or a
    similar feature the plain orthography does not write.
  - Keep it to the usual romanisation: at most 4 letters, and only that many
    for a syllable. Do not spell out a letter
    name ("ny", not "enye").
  - If a letter is a syllable rather than a single sound, give the whole
    syllable ("nga", not "ng").
  - If you do not recognise a letter, return an empty "spell" and say so in
    "why" rather than guessing."""


def ask(prompt: str, retries: int = 3) -> str:
    key = os.environ["GEMINI_API_KEY"]
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{MODEL}:generateContent?key={key}")
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.2,
                                            "maxOutputTokens": 8192}}).encode()
    for a in range(retries):
        try:
            req = urllib.request.Request(url, data=body,
                                         headers={"Content-Type": "application/json"})
            d = json.load(urllib.request.urlopen(req, timeout=300))
            return d["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            if a == retries - 1:
                raise
            time.sleep(4 * (a + 1))
    raise RuntimeError("unreachable")


def validate(entry: dict) -> tuple[str, str] | None:
    ch = entry.get("char") or ""
    spell = str(entry.get("spell", ""))
    if len(ch) != 1:
        return None
    if spell and not re.fullmatch(r"[a-z]{1,4}", spell):
        return None
    return ch, spell


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, help="only scan N languages (for a quick pass)")
    args = ap.parse_args()

    files = corpus_files()
    print("scanning corpora for letters no table covers ...", flush=True)
    seen = survey(files, args.limit)
    if not seen:
        print("nothing uncovered")
        return
    lines = []
    for ch, e in sorted(seen.items(), key=lambda kv: -kv[1]["count"]):
        langs = ", ".join(k for k, _ in e["langs"].most_common(3))
        words = ", ".join(e["words"][:3])
        lines.append(f"  {ch!r}  U+{ord(ch):04X}  {unicodedata.name(ch, '?')}\n"
                     f"      seen {e['count']}x in: {langs}\n"
                     f"      in words: {words}")
    print(f"{len(seen)} letters uncovered\n" + "\n".join(lines), flush=True)
    if args.dry_run:
        return

    raw = ask(PROMPT.format(letters="\n".join(lines)))
    m = re.search(r"\{.*\}", raw, re.S)
    data = json.loads(m.group(0)) if m else {}

    accepted, rejected = {}, []
    for entry in data.get("letters") or []:
        ok = validate(entry)
        if ok is None:
            rejected.append(entry)
            continue
        ch, spell = ok
        if ch not in seen:
            rejected.append(entry)
            continue
        accepted[ch] = spell

    tbl = json.loads(FALLBACK.read_text(encoding="utf-8"))
    added = {c: s for c, s in accepted.items() if s}
    dropped = [c for c, s in accepted.items() if not s]
    tbl["spell"].update(added)
    tbl["spell"] = dict(sorted(tbl["spell"].items()))
    tbl["drop"] = sorted(set(tbl.get("drop", [])) | set(dropped))
    tbl.setdefault("sourced_from_model", {})
    tbl["sourced_from_model"].update(
        {c: {"spell": accepted[c], "model": MODEL} for c in accepted})
    FALLBACK.write_text(json.dumps(tbl, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"\nadded {len(added)} spellings, {len(dropped)} marked as written-as-nothing, "
          f"{len(rejected)} rejected")
    for c, s in sorted(added.items()):
        print(f"    {c!r} -> {s!r}")
    for e in rejected[:6]:
        print(f"    rejected: {e}")


if __name__ == "__main__":
    main()
