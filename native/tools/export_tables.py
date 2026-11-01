#!/usr/bin/env python3
"""Export africa-g2p's *effective* runtime tables to afrig2p data files.

africa-g2p builds its tables at import time (majority votes, single-phoneme
filters, tie-bar normalisation, NFD keys ...). Rather than re-implementing that
build logic in C, we let the Python package build them and dump the final
dictionaries the converter actually consults. The C engine then only has to
implement the per-text algorithms, which keeps the two sides in lock-step.

Usage (from the africa-g2p repository; --src defaults to its src/ directory):
    python3 native/tools/export_tables.py twi fat ewe gaa dag
    python3 native/tools/export_tables.py --all

Output: one self-contained ``<lang>.afg2p`` file per language (UTF-8 text).

File format (version 1):
    afrig2p 1                      first line, magic + version
    [section]                      section header
    key<TAB>value                  map entry   (value may be empty)
    key                            set entry
Fields escape backslash, tab, LF and CR as \\\\ \\t \\n \\r.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

FORMAT_VERSION = 1


def esc(s: str) -> str:
    return (s.replace("\\", "\\\\").replace("\t", "\\t")
             .replace("\n", "\\n").replace("\r", "\\r"))


def write_map(fh, name, items):
    fh.write(f"[{name}]\n")
    for k, v in items:
        fh.write(f"{esc(k)}\t{esc(v)}\n")


def write_set(fh, name, keys):
    fh.write(f"[{name}]\n")
    for k in keys:
        fh.write(f"{esc(k)}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    here = Path(__file__).resolve().parent
    ap.add_argument("--src", default=str(here.parent.parent / "src"),
                    help="africa-g2p 'src' directory (default: this repository's)")
    ap.add_argument("--out", default=str(here.parent / "data"), help="output directory")
    ap.add_argument("--all", action="store_true",
                    help="every language: all rule files plus plain-Latin passthrough ones")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("langs", nargs="*", help="ISO 639-3 codes, e.g. twi fat ewe gaa")
    args = ap.parse_args()
    if not args.langs and not args.all:
        ap.error("give language codes or --all")

    sys.path.insert(0, str(Path(args.src).resolve()))
    import warnings
    warnings.simplefilter("ignore")
    import africa_g2p
    from africa_g2p import G2P, GraphemeConverter, UNIVERSAL, available_languages
    from africa_g2p.loader import LanguageNotFoundError
    from africa_g2p import convert as C
    from africa_g2p import fallback as F
    from africa_g2p import normalizer as N

    version = getattr(africa_g2p, "__version__", "unknown")
    commit = "unknown"
    try:  # exact provenance of the tables when exporting from a git checkout
        import subprocess
        commit = subprocess.run(
            ["git", "-C", str(Path(args.src).resolve()), "describe", "--always",
             "--dirty", "--abbrev=12"], capture_output=True, text=True,
            check=True).stdout.strip()
    except Exception:
        pass
    spell, drop = C._fallback()
    pairs = sorted(N._AFFRICATE_PAIRS, key=lambda p: -len(p[0] + p[1]))

    langs = list(args.langs)
    if args.all:
        langs = sorted(set(available_languages()) | set(C.plain_latin_languages()))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n_ipa = n_bad = 0
    for lang in langs:
        conv = GraphemeConverter(lang, UNIVERSAL)
        try:
            fwd = G2P(lang, output="ipa")        # same engine GraphemeConverter uses
            graphemes, diacritics = fwd.graphemes, fwd.diacritics
        except LanguageNotFoundError:
            # Plain-Latin language declared without a rule file: universal output is
            # a passthrough, and there is no IPA table (Python raises; C returns NULL).
            fwd, graphemes, diacritics = None, {}, {}
        path = out / f"{lang}.afg2p"
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(f"afrig2p {FORMAT_VERSION}\n")
            write_map(fh, "meta", [
                ("lang", lang),
                ("africa_g2p_version", version),
                ("africa_g2p_commit", commit),
                ("passthrough", "1" if conv.passthrough else "0"),
                ("ipa", "1" if fwd is not None else "0"),
            ])
            # --- per-language tables ------------------------------------------
            write_map(fh, "graphemes", sorted(graphemes.items()))
            write_map(fh, "diacritics", sorted(diacritics.items()))
            write_map(fh, "source_spelling", sorted(conv._source_spelling.items()))
            # --- shared universal / normaliser tables -------------------------
            write_map(fh, "universal_reverse", sorted(conv._universal_reverse.items()))
            # Only single-character keys can ever match (looked up per char).
            write_map(fh, "fallback_spell",
                      sorted((k, v) for k, v in spell.items() if len(k) == 1))
            write_set(fh, "fallback_drop", sorted(k for k in drop if len(k) == 1))
            write_map(fh, "fallback_ipa", sorted(F.FALLBACK_IPA.items()))
            write_set(fh, "spacing_tone", sorted(F.SPACING_TONE))
            write_map(fh, "confusables", sorted(N._CONFUSABLES.items()))
            write_set(fh, "orthographic_accents",
                      sorted(chr(c) for c in N._ORTHOGRAPHIC_ACCENTS))
            write_map(fh, "ligatures", list(N._LIGATURES.items()))     # order matters
            write_map(fh, "affricate_pairs", pairs)                    # order matters
            write_map(fh, "ascii_punct", sorted(C._ASCII_PUNCT.items()))
            write_set(fh, "apostrophes", sorted(set(C._APOSTROPHES)))
            write_set(fh, "vowels", sorted(C._VOWELS))
            write_map(fh, "vowel_alternatives",
                      sorted(C._UNIVERSAL_VOWEL_ALTERNATIVES.items()))
            write_set(fh, "aspiration", sorted(chr(c) for c in C._ASPIRATION_TRANS))
        # Every phoneme the table can emit must have a plain a-z universal spelling,
        # otherwise universal output would fall back to character-level guesses.
        bad = []
        if not conv.passthrough:
            for gr, ipa in sorted(graphemes.items()):
                spelled, _ = conv._map(ipa)
                if not all("a" <= c <= "z" for c in spelled):
                    bad.append(f"{gr}->{ipa}->{spelled!r}")
        n_ipa += fwd is not None
        n_bad += bool(bad)
        if args.verbose or len(langs) <= 20 or bad and len(langs) <= 20:
            print(f"wrote {path}  ({len(graphemes)} graphemes, "
                  f"passthrough={conv.passthrough}, ipa={fwd is not None})")
        if bad and (args.verbose or len(langs) <= 20):
            for b in bad:
                print(f"  WARNING universal spelling not plain a-z: {b}")
    print(f"exported {len(langs)} languages to {out} ({n_ipa} with IPA tables, "
          f"commit {commit}); {n_bad} have phonemes without a plain a-z universal spelling")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
