#!/usr/bin/env python3
"""Ask a model to diagnose why a language does not round-trip.

The mechanical work is done first: convert real corpus sentences, diff them
against the original, and count which substitutions actually occur. The model
is then given that evidence plus the language's own table and asked what is
wrong -- specifically whether a mismatch is a table error we should fix, or
legitimate orthographic variation in the source that we should normalise.

That second judgement is the one worth asking for. A mechanical test cannot
tell "le and lé are sloppy spelling of one word" from "le and lé are different
words because tone is phonemic", and the answer decides whether normalising the
orthography is a fix or a corruption.

    GEMINI_API_KEY=... python scripts/audit_reversibility.py --codes kus fat ewe
    GEMINI_API_KEY=... python scripts/audit_reversibility.py --worst 20
"""

from __future__ import annotations

import argparse
import collections
import difflib
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from africa_g2p import GraphemeConverter, UNIVERSAL_REVERSIBLE           # noqa: E402
from africa_g2p.convert import stored_universal               # noqa: E402
from africa_g2p.loader import load_rules                      # noqa: E402
from africa_g2p.normalizer import normalize_text              # noqa: E402

CORPUS = "AfriSpeech/africa-corpus"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-pro-preview")


def token() -> str:
    return (os.environ.get("HF_TOKEN")
            or (Path.home() / ".cache/huggingface/token").read_text().strip())


def corpus_files() -> dict[str, tuple[str, str]]:
    req = urllib.request.Request(f"https://huggingface.co/api/datasets/{CORPUS}",
                                 headers={"Authorization": f"Bearer {token()}"})
    out = {}
    for s in json.load(urllib.request.urlopen(req, timeout=120))["siblings"]:
        m = re.match(r"^(.*)_([a-z]{3})_v\d+\.csv$", s["rfilename"])
        if m:
            out.setdefault(m.group(2), (m.group(1).replace("_", " "), s["rfilename"]))
    return out


def evidence(code: str, files, n: int = 30) -> dict | None:
    """Mechanical diagnosis: what actually breaks, and how often."""
    if code not in files:
        return None
    name, fname = files[code]
    url = (f"https://huggingface.co/datasets/{CORPUS}/resolve/main/"
           + urllib.parse.quote(fname))
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token()}",
                                               "Range": "bytes=0-300000"})
    raw = urllib.request.urlopen(req, timeout=120).read().decode("utf-8", "replace")
    texts = [l.split(",", 2)[2].strip() for l in raw.splitlines()[1:]
             if l.count(",") >= 2]
    sample = [t for t in texts if t][:n]
    if not sample:
        return None

    f = GraphemeConverter(code, UNIVERSAL_REVERSIBLE)
    b = GraphemeConverter(UNIVERSAL_REVERSIBLE, code)
    subs: collections.Counter = collections.Counter()
    failures = []
    ok = 0
    for t in sample:
        want = normalize_text(t)
        back = b.convert(f.convert(t))
        if back == want:
            ok += 1
            continue
        sm = difflib.SequenceMatcher(None, want, back, autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op != "equal":
                subs[(want[i1:i2][:8], back[j1:j2][:8])] += 1
        if len(failures) < 4:
            failures.append({"source": want[:150], "universal": f.convert(t)[:150],
                             "back": back[:150]})

    # does the corpus spell the same skeleton more than one way?
    def strip_marks(w):
        return "".join(c for c in unicodedata.normalize("NFD", w)
                       if not unicodedata.combining(c))
    words = collections.Counter(w for t in texts
                                for w in re.findall(r"[^\W\d_]+", t.lower()))
    groups: dict[str, set] = collections.defaultdict(set)
    for w in words:
        groups[strip_marks(w)].add(w)
    varied = {k: sorted(v) for k, v in groups.items() if len(v) > 1}

    return {"code": code, "name": name, "exact": ok, "n": len(sample),
            "subs": subs.most_common(12), "failures": failures,
            "variant_examples": list(varied.items())[:8],
            "variant_rate": round(100 * len(varied) / max(len(groups), 1), 1)}


PROMPT = """You are auditing a grapheme-to-phoneme system for {name} ({code}).

Text is converted to a shared "universal" grapheme form and then back to {name}
orthography. It should return the original. It does not, for {fail} of {n}
sentences.

THE LANGUAGE'S TABLE (grapheme -> IPA):
{graphemes}

GRAPHEME -> UNIVERSAL, as currently generated:
{universal}

WHAT ACTUALLY GOES WRONG (wanted -> produced, with counts):
{subs}

EXAMPLES:
{examples}

ORTHOGRAPHIC VARIATION IN THE SOURCE CORPUS:
{variant_rate}% of word skeletons appear with more than one diacritic pattern.
Examples: {variants}

Answer these, briefly and concretely:

1. For each frequent substitution above, is it (a) a table error we should fix,
   (b) unavoidable information loss, or (c) legitimate variation in the source?

2. The variation examples: are those the SAME word spelled inconsistently, or
   DIFFERENT words distinguished by tone or nasalisation? This decides whether
   normalising the orthography would fix the problem or destroy meaning. Say
   which, for each example, and say if you are unsure.

3. Is there a standard or web-dominant orthography for {name} we should
   normalise to? Name it if so.

4. What single change would most improve round-trip fidelity here?

Be specific to this language. If the evidence does not support a confident
answer, say so rather than guessing."""


def ask(prompt: str) -> str:
    key = os.environ["GEMINI_API_KEY"]
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{MODEL}:generateContent?key={key}")
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.3,
                                            "maxOutputTokens": 4096}}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=300))
    return d["candidates"][0]["content"]["parts"][0]["text"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", nargs="*")
    ap.add_argument("--worst", type=int, help="audit the N worst-scoring languages")
    ap.add_argument("--out", default=str(Path.home() / "audit"))
    args = ap.parse_args()

    files = corpus_files()
    codes = args.codes or []
    if args.worst:
        rep = json.loads((REPO / "src/africa_g2p/data/reversibility.json")
                         .read_text(encoding="utf-8"))
        codes = [r["code"] for r in rep if r.get("sentences")][-args.worst:]

    os.makedirs(args.out, exist_ok=True)
    for code in codes:
        ev = evidence(code, files)
        if not ev:
            print(f"  {code}: no corpus"); continue
        rules = load_rules(code)
        fwd, _ = stored_universal(code)
        prompt = PROMPT.format(
            name=ev["name"], code=code, fail=ev["n"] - ev["exact"], n=ev["n"],
            graphemes=json.dumps(rules.get("graphemes", {}), ensure_ascii=False)[:2500],
            universal=json.dumps(fwd, ensure_ascii=False)[:2500],
            subs="\n".join(f"   {w!r} -> {g!r}   x{c}" for (w, g), c in ev["subs"]),
            examples="\n".join(
                f"   src : {x['source']}\n   uni : {x['universal']}\n"
                f"   back: {x['back']}\n" for x in ev["failures"]),
            variant_rate=ev["variant_rate"],
            variants=", ".join(f"{k}: {v}" for k, v in ev["variant_examples"][:6]),
        )
        try:
            answer = ask(prompt)
        except Exception as exc:
            print(f"  {code}: model call failed {type(exc).__name__}"); continue
        path = Path(args.out) / f"{code}.md"
        path.write_text(f"# {ev['name']} ({code})\n\n"
                        f"{ev['exact']}/{ev['n']} sentences exact, "
                        f"{ev['variant_rate']}% variant skeletons\n\n{answer}\n",
                        encoding="utf-8")
        print(f"  {code} {ev['name'][:22]:<24} {ev['exact']}/{ev['n']} exact "
              f"-> {path}", flush=True)


if __name__ == "__main__":
    main()
