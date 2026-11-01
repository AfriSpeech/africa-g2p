#!/usr/bin/env python3
"""Parity test: afrig2p (C) must match africa-g2p (Python) exactly.

    python3 native/tests/parity.py twi fat ewe gaa dag      # from the repo root
    python3 native/tests/parity.py --all --fuzz 200         # every exported language

Compares, for every input line and for sep in ("", " "):
    GraphemeConverter(lang, "universal").convert(line, sep)  vs  afrig2p_to_universal
    G2P(lang, output="ipa").convert(line, sep)              vs  afrig2p_to_ipa

Inputs: the package's own showcase sentences for the language, upstream test
strings, a hand-written edge-case list, optional --corpus files (one sentence
per line, e.g. your TTS transcripts), and --fuzz N random strings.

The English-loanword skip is pinned on both sides: --english none (default)
disables it; --english FILE uses the same word list in Python and C.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import random
import sys
import warnings
from pathlib import Path

EDGE_CASES = [
    "", " ", "Akwaaba!", "Onyankopɔn", "dodoɔ", "hyɛɛ", "Google is great",
    "Me din de Kwame. Ɛte sɛn?", "kpako nyini", "Ŋdi na wò", "Mɛni ji o gbɛi?",
    "ŋmɛnɛ", "ɔ̃ ɛ̃ ã", "Ɔno na ɔbaa", "tsɛ", "shwɛ", "DWƐ KYƐ", "nkwa'a",
    "‘quoted’ «text» — dash… 3½ km", "ʧiʤi", "tʰa kʰo", "aˈba", "ẹgbẹ ọṣọ",
    "ተማሪ", "Москва", "مرحبا", "emoji 😀 ok", "tab\there", "İstanbul",
    "é à ô ū", "Kofi Annan 1938-2018",
]

FUZZ_CHARS = (
    "abcdefghijklmnopqrstuvwxyz" "ABCDEFGHIJKLMNOPRSTUWYZ"
    "ɛɔŋɖƒɣʋəƐƆŊƉƑƔƲ" "ãẽĩõũ" "ẹọṣ" "áàâǎāéèíìóòúù"
    "̣̱̀́̂̃̄̌͡"
    "'’ʼ`ꞌ" "  \t" ".,;:!?-()\"«»“”‘’–—…·" "0123456789½²"
    "ˈˉˊˋ" "ʰʷʲː" "ʧʤʦ" "εοι" "абв" "ابت" "ሀለ" "ꕉ" "😀"
)


def fuzz_lines(n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        k = rng.randint(1, 40)
        out.append("".join(rng.choice(FUZZ_CHARS) for _ in range(k)))
    return out


class CLib:
    def __init__(self, path: str):
        lib = ctypes.CDLL(path)
        lib.afrig2p_create_from_file.restype = ctypes.c_void_p
        lib.afrig2p_create_from_file.argtypes = [ctypes.c_char_p,
                                                 ctypes.POINTER(ctypes.c_void_p)]
        lib.afrig2p_set_english_words.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                                  ctypes.c_size_t]
        for fn in (lib.afrig2p_to_universal, lib.afrig2p_to_ipa):
            fn.restype = ctypes.c_void_p
            fn.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.afrig2p_free.argtypes = [ctypes.c_void_p]
        lib.afrig2p_destroy.argtypes = [ctypes.c_void_p]
        self.lib = lib

    def load(self, path: Path, english: bytes | None):
        err = ctypes.c_void_p()
        h = self.lib.afrig2p_create_from_file(str(path).encode(), ctypes.byref(err))
        if not h:
            msg = ctypes.string_at(err.value).decode() if err.value else "load failed"
            raise RuntimeError(msg)
        if english is not None:
            self.lib.afrig2p_set_english_words(h, english, len(english))
        return h

    def call(self, fn, h, text: str, sep: str) -> str | None:
        p = fn(h, text.encode("utf-8"), sep.encode("utf-8"))
        if not p:
            return None
        try:
            return ctypes.string_at(p).decode("utf-8")
        finally:
            self.lib.afrig2p_free(p)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    native = Path(__file__).resolve().parent.parent
    lib_name = {"darwin": "libafrig2p.dylib", "win32": "afrig2p.dll"}.get(
        sys.platform, "libafrig2p.so")
    ap.add_argument("--src", default=str(native.parent / "src"),
                    help="africa-g2p src directory (default: this repository's)")
    ap.add_argument("--lib", default=str(native / "build" / lib_name),
                    help="path to the libafrig2p shared library")
    ap.add_argument("--data", default=str(native / "data"),
                    help="directory with <lang>.afg2p")
    ap.add_argument("--all", action="store_true", help="every <lang>.afg2p in --data")
    ap.add_argument("--english", default="none", help="'none' or a word-list file")
    ap.add_argument("--corpus", nargs="*", default=[], help="extra text files")
    ap.add_argument("--fuzz", type=int, default=2000, help="random strings per lang")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--show", type=int, default=10, help="mismatches to print")
    ap.add_argument("langs", nargs="*")
    args = ap.parse_args()
    if args.all:
        args.langs = sorted(p.stem for p in Path(args.data).glob("*.afg2p"))
    if not args.langs:
        ap.error("give language codes or --all")

    src = Path(args.src).resolve()
    sys.path.insert(0, str(src))
    warnings.simplefilter("ignore")
    from africa_g2p import G2P, GraphemeConverter, UNIVERSAL
    from africa_g2p import convert as C
    from africa_g2p.loader import LanguageNotFoundError

    # Pin the English-loanword skip so both sides use the same rule.
    eng_bytes = None
    if args.english == "none":
        C._is_english_word = lambda w: False
    else:
        eng_bytes = Path(args.english).read_bytes()
        words = {ln.strip().lower() for ln in eng_bytes.decode("utf-8").splitlines()
                 if len(ln.strip()) >= 3}
        C._is_english_word = lambda w: (len(w) >= 3 and w.isalpha() and w.isascii()
                                        and w.lower() in words)

    showcase = {}
    sc_path = src.parent / "docs" / "showcase.json"
    if sc_path.exists():
        for entry in json.loads(sc_path.read_text(encoding="utf-8")):
            showcase[entry["code"]] = [s["text"] for s in entry.get("samples", [])]

    extra = []
    for f in args.corpus:
        extra += Path(f).read_text(encoding="utf-8").splitlines()

    clib = CLib(args.lib)
    total_fail = total_checks = failed_langs = 0
    for lang in args.langs:
        h = clib.load(Path(args.data) / f"{lang}.afg2p", eng_bytes)
        conv = GraphemeConverter(lang, UNIVERSAL)
        try:
            g2p = G2P(lang, output="ipa")
        except LanguageNotFoundError:  # plain-Latin, no rule file: C must return NULL
            g2p = None
        lines = (showcase.get(lang, []) + EDGE_CASES + extra
                 + fuzz_lines(args.fuzz, args.seed + sum(map(ord, lang))))
        checks = fails = 0
        shown = 0
        for line in lines:
            for sep in ("", " "):
                for name, py_fn, c_fn in (
                    ("universal", lambda t, s: conv.convert(t, sep=s),
                     clib.lib.afrig2p_to_universal),
                    ("ipa", (lambda t, s: g2p.convert(t, sep=s)) if g2p else
                     (lambda t, s: None), clib.lib.afrig2p_to_ipa),
                ):
                    checks += 1
                    want = py_fn(line, sep)
                    got = clib.call(c_fn, h, line, sep)
                    if want != got:
                        fails += 1
                        if shown < args.show:
                            shown += 1
                            print(f"  MISMATCH {lang} {name} sep={sep!r}\n"
                                  f"    in : {line!r}\n    py : {want!r}\n    c  : {got!r}")
        clib.lib.afrig2p_destroy(h)
        status = "OK  " if fails == 0 else "FAIL"
        if fails or len(args.langs) <= 20:
            print(f"{status} {lang}: {checks - fails}/{checks} identical "
                  f"({len(showcase.get(lang, []))} showcase lines, {args.fuzz} fuzz)")
        total_fail += fails
        total_checks += checks
        failed_langs += bool(fails)
    print(f"{'PASS' if not total_fail else 'FAIL'}: {len(args.langs)} languages, "
          f"{total_checks - total_fail}/{total_checks} identical, "
          f"{failed_langs} languages with mismatches")
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
