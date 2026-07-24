"""Text normalization: splitting into word / non-word tokens for the G2P engine.

Kept deliberately light-touch. African orthographies in the Hartell reference are
largely phonemic, so normalization is mostly about (a) Unicode normalization,
(b) case folding, and (c) separating pronounceable word tokens from punctuation and
whitespace that should pass through untouched.
"""
from __future__ import annotations

import re
import unicodedata
from typing import List, NamedTuple


class Token(NamedTuple):
    text: str
    is_word: bool


# A "word" is a run of letters/marks/apostrophes; everything else is a separator.
# \w is Unicode-aware under re.UNICODE (default in py3), covering ɛ ɔ ŋ etc.
_WORD_RE = re.compile(r"[^\W\d_]+(?:['’ʼ̀-ͯ][^\W\d_]*)*", re.UNICODE)

# Visually-confusable characters that appear in the scanned source where a specific
# Latin/IPA orthographic letter is meant. Folded on both grapheme keys and input text
# so they compare equal. This is the *orthographic* domain, distinct from phoneme values.
_CONFUSABLES = {
    "ε": "ɛ",  # Greek epsilon ε -> Latin open e ɛ
    "ι": "ɩ",  # Greek iota ι -> Latin iota ɩ
    "ɡ": "g",       # IPA script g ɡ -> ASCII g
    "ı": "i",       # dotless i ı -> i
    "’": "'",       # right single quote -> apostrophe
    "ʼ": "'",       # modifier apostrophe -> apostrophe
}
_CONFUSABLE_TABLE = {ord(k): v for k, v in _CONFUSABLES.items()}


def fold_confusables(text: str) -> str:
    """Fold visually-confusable orthographic characters to a canonical form."""
    return text.translate(_CONFUSABLE_TABLE)


def normalize_text(text: str, *, lower: bool = True) -> str:
    """Unicode-normalize (NFC), fold confusables, and optionally case-fold."""
    text = unicodedata.normalize("NFC", text)
    text = fold_confusables(text)
    if lower:
        text = text.lower()
    return text


def tokenize(text: str) -> List[Token]:
    """Split into alternating word / non-word tokens, preserving order and content."""
    tokens: List[Token] = []
    pos = 0
    for m in _WORD_RE.finditer(text):
        if m.start() > pos:
            tokens.append(Token(text[pos:m.start()], False))
        tokens.append(Token(m.group(), True))
        pos = m.end()
    if pos < len(text):
        tokens.append(Token(text[pos:], False))
    return tokens
