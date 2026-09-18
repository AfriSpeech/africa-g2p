#!/usr/bin/env python3
"""Build the global proxy escape table.

Proxy writes any orthography in plain a-z so that the original comes back
exactly. The per-language version of this allocated a spelling per language and
checked it for collisions, which took four rounds of collision bugs to get
working and still left 175 languages short of a clean round trip.

This is the systematic alternative. One table for every language, and the code
is decodable by construction rather than by checking:

    every a-z letter   ->  itself
    literal x          ->  xx
    anything else      ->  x <payload> x        e.g.  ɔ -> xox,  ŋ -> xngx

Reading it back is a scan: an "x" starts an escape, "xx" is a literal x, and
otherwise the code runs to the next "x". Nothing else can be misread, so no
language needs checking and none can fail.

Payloads start from how the letter is written in universal -- ɔ is o, ŋ is ng --
so an escape stays legible, and gain a suffix only where two letters would
otherwise want the same payload.

    python scripts/build_proxy_escapes.py
"""

from __future__ import annotations

import argparse
import collections
import json
import string
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LANG_DIR = REPO / "src" / "africa_g2p" / "languages"
OUT = REPO / "src/africa_g2p/data/proxy_escapes.json"
sys.path.insert(0, str(REPO / "src"))


def wanted_characters() -> collections.Counter:
    """Every non-a-z character any chart writes, by how many charts write it."""
    from africa_g2p.convert import _APOSTROPHES
    seen: collections.Counter = collections.Counter()
    for p in sorted(LANG_DIR.glob("*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for k in (t.get("graphemes") or {}):
            for ch in unicodedata.normalize("NFD", k):
                if "a" <= ch <= "z" or not ch.strip():
                    continue
                seen[ch] += 1
    for ch in _APOSTROPHES:
        seen[ch] += 1
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from africa_g2p.convert import universal_fallback

    seen = wanted_characters()
    print(f"{len(seen)} characters need an escape")

    # Tone marks read better with a mnemonic of their own than with whatever
    # the romaniser happens to give them.
    MARKS = {"\u0301": "q", "\u0300": "w", "\u0302": "wq", "\u030c": "qw",
             "\u0304": "mq", "\u0303": "nq", "\u0308": "jq", "\u0323": "vq",
             "\u0307": "jj", "\u0331": "mm", "\u0327": "vv"}

    ALPHABET = string.ascii_lowercase.replace("x", "")

    def free(base: str, used: set) -> str:
        """base, else base+letter, else base+letter+letter -- never unbounded.

        Never "zz...": that prefix is reserved for a character with no entry
        here at all, which is encoded from its codepoint instead, so proxy
        cannot be defeated by a letter nobody tabulated.
        """
        if base.startswith("zz"):
            base = "z" + base[2:]
        if base and base not in used and not base.startswith("zz"):
            return base
        for a in ALPHABET:
            if base + a not in used and not (base + a).startswith("zz"):
                return base + a
        for a in ALPHABET:
            for b in ALPHABET:
                if base + a + b not in used and not (base + a + b).startswith("zz"):
                    return base + a + b
        raise RuntimeError(f"no free payload for {base!r}")

    payloads: dict = {}
    used: set = set()
    for ch, code in MARKS.items():
        if ch in seen:
            payloads[ch] = code
            used.add(code)
    # commonest first, so the shortest payloads go to the letters most text uses
    for ch, _ in seen.most_common():
        if ch in payloads:
            continue
        base = universal_fallback(ch) or ""
        base = "".join(c for c in base if "a" <= c <= "z" and c != "x")
        if not base:
            base = "z"
        payloads[ch] = free(base, used)
        used.add(payloads[ch])

    table = {
        "_comment": (
            "Global escape table for the proxy alphabet. Proxy writes any "
            "orthography in plain a-z and reads back exactly, without a "
            "per-language table: an a-z letter stands for itself, a literal x "
            "doubles to xx, and anything else is written x<payload>x -- ɔ is "
            "xox, ŋ is xngx, a combining acute is xqx. Reading back is a scan, "
            "so the code cannot be misread and no language can fail. Payloads "
            "start from the universal spelling of the letter so an escape stays "
            "legible, and take a suffix only where two letters would collide."),
        "escape": "x",
        "literal_escape": "xx",
        "payloads": {k: v for k, v in sorted(payloads.items())},
    }
    longest = max(len(v) for v in payloads.values())
    print(f"   payloads: {len(payloads)}, longest {longest} letters")
    show = [(c, payloads[c]) for c, _ in seen.most_common(14)]
    print("   commonest:", "  ".join(f"{c}->x{p}x" for c, p in show))
    if args.dry_run:
        return
    OUT.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nwritten to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
