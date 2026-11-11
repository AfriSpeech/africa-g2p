"""Dictionary-based code-switching phonemization for African languages.

Converts English loanwords, nouns, and named entities embedded in African-language
text into English IPA (espeak-ng) while preserving the surrounding words in native
African G2P.
"""
from __future__ import annotations

import gzip
import re
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent / "data"
_DEFAULT_LEXICON_TSV = _DATA_DIR / "codeswitch_en.tsv"
_DEFAULT_LEXICON_GZ = _DATA_DIR / "codeswitch_en.tsv.gz"

_PUNCT_RE = re.compile(r"^(\W*)(.*?)(\W*)$", re.DOTALL)


@lru_cache(maxsize=4)
def load_codeswitch_dict(path: str | Path | None = None) -> dict[str, str]:
    """Load a code-switching lexicon (word/phrase -> espeak IPA)."""
    p = Path(path) if path else (_DEFAULT_LEXICON_TSV if _DEFAULT_LEXICON_TSV.exists() else _DEFAULT_LEXICON_GZ)
    if not p.exists():
        return {}
    lexicon: dict[str, str] = {}
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                lexicon[parts[0].lower()] = parts[1]
    return lexicon


def convert_codeswitch(text: str, lang: str, lexicon: dict[str, str], g2p_func) -> str:
    """Phonemize `text` in `lang`, substituting words/phrases present in `lexicon`
    with their precomputed English IPA, and routing other words to `g2p_func(word, lang)`."""
    if not text.strip():
        return text
    words = text.split()
    out: list[str] = []
    i = 0
    n = len(words)
    while i < n:
        # Longest match: try 3 words, 2 words, 1 word
        matched = False
        for k in (3, 2, 1):
            if i + k <= n:
                window = words[i:i + k]
                lead, first_core, _ = _PUNCT_RE.match(window[0]).groups()
                _, last_core, trail = _PUNCT_RE.match(window[-1]).groups()
                if k == 1:
                    phrase_core = first_core.lower()
                else:
                    middle = [_PUNCT_RE.match(w).groups()[1].lower() for w in window[1:-1]]
                    phrase_core = " ".join([first_core.lower()] + middle + [last_core.lower()])

                if phrase_core in lexicon:
                    ipa = lexicon[phrase_core]
                    out.append(lead + ipa + trail)
                    i += k
                    matched = True
                    break
        if not matched:
            lead, core, trail = _PUNCT_RE.match(words[i]).groups()
            if core:
                ipa = g2p_func(core, lang)
                out.append(lead + ipa + trail)
            else:
                out.append(words[i])
            i += 1
    return " ".join(out)
