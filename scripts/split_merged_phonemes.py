#!/usr/bin/env python3
"""Ask a model whether graphemes sharing one IPA value are really one phoneme.

Some charts give two letters of the same script the same phoneme: Dan writes
both <bh> and <m> as /ɓ/, Ngiemboon writes both <b> and <p> as /b/. Sometimes
that is real (a letter genuinely has no separate sound), and sometimes the chart
has recorded an *allophony* rule -- [m] is how /ɓ/ surfaces before a nasal vowel
-- and thrown the letters away in the process.

A mechanical test cannot tell those apart, so it is asked, one merged set at a
time, with the corpus to hand.

This deliberately does NOT regenerate whole charts. Re-running the original
prompt would likely reproduce the merge it created; and a whole-chart rewrite
puts every correct entry at risk to fix one wrong one. Only the graphemes in a
merged set can change, and every other key is copied through untouched.

    GEMINI_API_KEY=... python scripts/split_merged_phonemes.py --codes daf nnh
    GEMINI_API_KEY=... python scripts/split_merged_phonemes.py --all --workers 4
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
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
LANG_DIR = REPO / "src" / "africa_g2p" / "languages"
sys.path.insert(0, str(REPO / "src"))
from africa_g2p.loader import load_rules            # noqa: E402

CORPUS = "AfriSpeech/africa-corpus"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-pro-preview")


def hf_token() -> str:
    return (os.environ.get("HF_TOKEN")
            or (Path.home() / ".cache/huggingface/token").read_text().strip())


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


def merged_sets(graphemes: dict) -> dict:
    """{ipa: [graphemes]} for graphemes of the SAME script sharing one value.

    Cross-script sharing is excluded on purpose: Ethiopic ሀ and its romanisation
    "ha" are two writings of one sound and are meant to agree.
    """
    inv: dict = collections.defaultdict(list)
    for k, v in graphemes.items():
        inv[str(v)].append(k)
    out = {}
    for ipa, ks in inv.items():
        if len(ks) < 2:
            continue
        by: dict = collections.defaultdict(list)
        for k in ks:
            by[graph_script(k)].append(k)
        for lst in by.values():
            distinct = {unicodedata.normalize("NFC", x.lower()) for x in lst}
            if len(distinct) > 1:
                out[ipa] = sorted(lst)
    return out


def corpus_files() -> dict:
    req = urllib.request.Request(f"https://huggingface.co/api/datasets/{CORPUS}",
                                 headers={"Authorization": f"Bearer {hf_token()}"})
    out = {}
    for s in json.load(urllib.request.urlopen(req, timeout=120))["siblings"]:
        m = re.match(r"^(.*)_([a-z]{3})_v\d+\.csv$", s["rfilename"])
        if m:
            out[m.group(2)] = (m.group(1).replace("_", " "), s["rfilename"])
    return out


def corpus_words(fname: str, graphs: list, nbytes: int = 300_000) -> dict:
    """Real words containing each merged grapheme -- evidence, not memory."""
    url = (f"https://huggingface.co/datasets/{CORPUS}/resolve/main/"
           + urllib.parse.quote(fname))
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {hf_token()}",
                                               "Range": f"bytes=0-{nbytes}"})
    raw = urllib.request.urlopen(req, timeout=120).read().decode("utf-8", "replace")
    words = [w for l in raw.splitlines()[1:] if l.count(",") >= 2
             for w in re.findall(r"[^\W\d_]+", l.split(",", 2)[2].lower())]
    freq = collections.Counter(words)
    out = {}
    for g in graphs:
        hits = [w for w in freq if g.lower() in w]
        hits.sort(key=lambda w: -freq[w])
        out[g] = hits[:12]
    return out


PROMPT = """You are correcting one specific defect in a grapheme-to-phoneme table
for {name} ({code}).

These graphemes are all recorded with the SAME IPA value. They are all in the
same script, so this is not a romanisation pairing -- the table is claiming the
letters are pronounced identically.

{sets}

REAL WORDS FROM THE {code} CORPUS CONTAINING EACH GRAPHEME:
{words}

THE REST OF THE TABLE (do not change any of these):
{rest}

For each merged set decide, using the corpus evidence:

(a) GENUINE -- the letters really do spell one phoneme in this language. Free
    variation or a spelling convention. Leave them alone.
(b) ALLOPHONY RECORDED WRONGLY -- the letters spell different phonemes, and
    what got recorded is a rule about how one surfaces in some environment.
    For example writing <m> as /ɓ/ because [m] is how /ɓ/ appears before a
    nasal vowel: <m> should simply be /m/.
(c) ERROR -- the letters spell different phonemes and the value is a mistake.

Return ONLY JSON, no prose:

{{"sets": [{{"ipa": "<the shared value>",
            "verdict": "genuine" | "allophony" | "error",
            "assign": {{"<grapheme>": "<its correct IPA>", ...}},
            "why": "<one sentence>"}}]}}

Rules for "assign":
  - include it only for verdict "allophony" or "error"; omit it for "genuine"
  - every key must be one of the graphemes of that set, spelled exactly
  - leave the grapheme that is genuinely the original sound at that value
  - values must be IPA, not orthography, and must not be empty
  - use U+0261 ɡ for a voiced velar plosive, never ASCII g
  - do not assign a value already used by a DIFFERENT grapheme in the rest of
    the table

If the corpus evidence does not support a confident answer, return "genuine"
and say so in "why". A wrong split is worse than leaving the merge in place."""


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


_IPA_OK = re.compile(r"^[^\sA-Za-z0-9]*$|^[a-zɑɐɒæɓɔɕçɖɗəɘɚɛɜɞɟɠɡɢʛɣɤɥɦɧħɨɪʝɭɬɫɮʟɰɱɲɳŋɴɵøɸθœɶʘɹɺɾɻʀʁʂʃʈʉʊʋⱱʌɣɤʍχʎʏʑʐʒʔʕʢʡǀǁǂǃˈˌːˑ̥̬̪̺̻̃̊͡ʰʱʲʷˤ˞βðŋθ̀-ͯ ]+$")


def validate(data: dict, graphemes: dict, sets: dict) -> tuple[dict, list]:
    """Return (accepted assignments, reasons anything was rejected)."""
    accepted, notes = {}, []
    # values used by graphemes that are NOT part of any merged set
    in_sets = {g for gs in sets.values() for g in gs}
    reserved = {str(v) for k, v in graphemes.items() if k not in in_sets}

    for entry in data.get("sets") or []:
        ipa = str(entry.get("ipa", ""))
        verdict = str(entry.get("verdict", "")).lower()
        if ipa not in sets:
            notes.append(f"unknown set {ipa!r}")
            continue
        if verdict == "genuine":
            continue
        assign = entry.get("assign") or {}
        if not isinstance(assign, dict) or not assign:
            notes.append(f"{ipa!r}: verdict {verdict} with no assignment")
            continue
        members = set(sets[ipa])
        ok = {}
        for g, val in assign.items():
            val = str(val).strip()
            if g not in members:
                notes.append(f"{ipa!r}: {g!r} is not in the set"); continue
            if not val:
                notes.append(f"{ipa!r}: {g!r} got an empty value"); continue
            if "g" in val:
                notes.append(f"{ipa!r}: {g!r} uses ASCII g"); continue
            if not _IPA_OK.match(val):
                notes.append(f"{ipa!r}: {g!r} value {val!r} is not IPA"); continue
            if val in reserved:
                notes.append(f"{ipa!r}: {g!r} value {val!r} collides"); continue
            ok[g] = val
        # the split must actually separate them, and must leave one behind
        if len(ok) == len(members):
            notes.append(f"{ipa!r}: every member reassigned, none left at {ipa!r}")
            continue
        if len(set(ok.values())) != len(ok):
            notes.append(f"{ipa!r}: assignment is not injective")
            continue
        accepted.update(ok)
        reserved.update(ok.values())
    return accepted, notes


def fix(code: str, files: dict) -> tuple:
    try:
        rules = load_rules(code)
    except Exception as exc:
        return code, 0, [f"load failed: {type(exc).__name__}"]
    graphemes = rules.get("graphemes") or {}
    sets = merged_sets(graphemes)
    if not sets:
        return code, 0, []
    if code not in files:
        return code, 0, ["no corpus"]
    name, fname = files[code]

    try:
        words = corpus_words(fname, sorted({g for gs in sets.values() for g in gs}))
    except Exception as exc:
        return code, 0, [f"corpus fetch failed: {type(exc).__name__}"]

    in_sets = {g for gs in sets.values() for g in gs}
    prompt = PROMPT.format(
        name=name, code=code,
        sets="\n".join(f"  {ipa!r}  <-  {gs}" for ipa, gs in sets.items()),
        words="\n".join(f"  {g!r}: {ws}" for g, ws in words.items() if ws),
        rest=json.dumps({k: v for k, v in graphemes.items() if k not in in_sets},
                        ensure_ascii=False)[:2000])
    try:
        raw = ask(prompt)
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception as exc:
        return code, 0, [f"model call failed: {type(exc).__name__}"]

    accepted, notes = validate(data, graphemes, sets)
    if not accepted:
        return code, 0, notes

    path = LANG_DIR / f"{code}.json"
    tbl = json.loads(path.read_text(encoding="utf-8"))
    for g, val in accepted.items():
        tbl["graphemes"][g] = val
    note = (f"{len(accepted)} grapheme(s) split off shared phoneme values by "
            f"{MODEL} against the {CORPUS} {code} corpus; not reviewed by a speaker.")
    tbl["source"] = (tbl.get("source", "") + " " + note).strip()
    path.write_text(json.dumps(tbl, ensure_ascii=False, indent=2), encoding="utf-8")

    # the chart must still load, and must not have gained a new merge
    try:
        again = merged_sets(load_rules(code).get("graphemes") or {})
    except Exception as exc:
        path.write_text(json.dumps(json.loads(path.read_text(encoding="utf-8")),
                                   ensure_ascii=False, indent=2), encoding="utf-8")
        return code, 0, [f"reload failed: {type(exc).__name__}"]
    if len(again) > len(sets):
        return code, 0, ["split created new merges"]
    return code, len(accepted), notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    codes = args.codes or []
    if args.all or args.list:
        codes = []
        for p in sorted(LANG_DIR.glob("*.json")):
            try:
                if merged_sets(load_rules(p.stem).get("graphemes") or {}):
                    codes.append(p.stem)
            except Exception:
                pass
    if args.list:
        print(f"{len(codes)} languages with same-script merged phonemes")
        print(" ".join(codes))
        return

    files = corpus_files()
    done = fixed = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for code, n, notes in ex.map(lambda c: fix(c, files), codes):
            done += 1
            fixed += n
            flag = f"{n} split" if n else "unchanged"
            print(f"  [{done}/{len(codes)}] {code:<6}{flag}"
                  + (f"   ({notes[0]})" if notes and not n else ""), flush=True)
    print(f"\n{fixed} graphemes split across {len(codes)} languages")


if __name__ == "__main__":
    main()
