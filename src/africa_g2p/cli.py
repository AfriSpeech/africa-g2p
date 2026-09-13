"""Command-line interface: ``africa-g2p <lang> "text"`` or ``--list``.

Cross-language conversion: ``africa-g2p twi "Onyankopɔn" --to ewe`` rewrites Twi's
graphemes in Ewe's; ``--to universal`` uses the majority grapheme for each phoneme.
"""
from __future__ import annotations

import argparse
import sys

from .convert import GraphemeConverter, UNIVERSAL, convert_lang, convert_to_ipa
from .g2p import G2P
from .loader import available_languages, registry, LanguageNotFoundError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="africa-g2p", description=__doc__)
    parser.add_argument("lang", nargs="?", help="ISO 639-3 language code")
    parser.add_argument("text", nargs="?", help="text to convert (or read stdin)")
    parser.add_argument("--sep", default=None,
                        help="separator between phoneme units (default: \" \" for G2P, "
                             "none for --to, i.e. words are kept whole)")
    parser.add_argument("--to", default=None,
                        help=f"rewrite graphemes into this language (or '{UNIVERSAL}') "
                             "instead of native output")
    parser.add_argument("--ipa", action="store_true",
                        help="print IPA via the universal pipeline "
                             "(graphemes -> universal -> IPA, the g2u2p route)")
    parser.add_argument("--list", action="store_true", help="list available languages")
    args = parser.parse_args(argv)

    if args.list or not args.lang:
        reg = registry()
        for code in available_languages():
            name = reg.get(code, {}).get("name", "")
            print(f"{code}\t{name}")
        return 0

    text = args.text if args.text is not None else sys.stdin.read()
    if args.ipa:
        print(convert_to_ipa(text, args.lang, sep=args.sep or " "))
        return 0
    if args.to:
        try:
            conv = GraphemeConverter(args.lang, args.to)
        except LanguageNotFoundError as e:
            print(e, file=sys.stderr)
            return 1
    else:
        try:
            conv = G2P(args.lang)
        except LanguageNotFoundError as e:
            print(e, file=sys.stderr)
            return 1
    sep = args.sep if args.sep is not None else ("" if args.to else " ")
    print(conv.convert(text, sep=sep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
