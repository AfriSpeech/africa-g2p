"""Command-line interface: ``africa-g2p <lang> "text"`` or ``--list``."""
from __future__ import annotations

import argparse
import sys

from .g2p import G2P
from .loader import available_languages, registry, LanguageNotFoundError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="africa-g2p", description=__doc__)
    parser.add_argument("lang", nargs="?", help="ISO 639-3 language code")
    parser.add_argument("text", nargs="?", help="text to convert (or read stdin)")
    parser.add_argument("--sep", default=" ", help="separator between phonemes")
    parser.add_argument("--list", action="store_true", help="list available languages")
    args = parser.parse_args(argv)

    if args.list or not args.lang:
        reg = registry()
        for code in available_languages():
            name = reg.get(code, {}).get("name", "")
            print(f"{code}\t{name}")
        return 0

    text = args.text if args.text is not None else sys.stdin.read()
    try:
        conv = G2P(args.lang)
    except LanguageNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    print(conv.convert(text, sep=args.sep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
