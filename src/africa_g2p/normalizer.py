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


def _mark_class() -> str:
    """Regex character class covering every combining mark in the BMP.

    Hardcoding the Latin combining block (U+0300-U+036F) split marks off as separators
    for every other script: Ethiopic gemination (U+135F), Arabic/Ajami vowel points,
    Hebrew points, N'Ko and Tifinagh marks all fell outside it, so keys containing them
    could never match. Deriving the class from Unicode covers all of them and costs
    ~20 ms once at import. Marks above the BMP are historic/musical and irrelevant here.
    """
    ranges, start, prev = [], None, None
    for cp in range(0x300, 0x10000):
        if unicodedata.category(chr(cp)) in ("Mn", "Mc"):
            if start is None:
                start = cp
            prev = cp
        elif start is not None:
            ranges.append((start, prev))
            start = None
    if start is not None:
        ranges.append((start, prev))
    return "".join(
        re.escape(chr(a)) if a == b else f"{re.escape(chr(a))}-{re.escape(chr(b))}"
        for a, b in ranges
    )


# A "word" is a run of letters/marks/apostrophes; everything else is a separator.
# \w is Unicode-aware under re.UNICODE (default in py3), covering ɛ ɔ ŋ etc.
_WORD_RE = re.compile(
    r"[^\W\d_]+(?:['’ʼ" + _mark_class() + r"][^\W\d_]*)*", re.UNICODE
)

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


# Orthographic tone / accent combining marks that must NEVER appear in IPA output.
# IPA renders tone with tone letters (˥˦˧˨˩) or spacing marks — not with vowel accents.
# This set deliberately EXCLUDES genuine IPA combining diacritics such as nasalization
# (U+0303), the affricate tie bar (U+0361/U+035C), extra-short (U+0306), centralized
# (U+0308), ATR (U+0318/U+0319), voiceless (U+0325), so those are preserved.
_ORTHOGRAPHIC_ACCENTS = {
    0x0300,  # grave (low tone)
    0x0301,  # acute (high tone)
    0x0302,  # circumflex (falling)
    0x0304,  # macron (mid tone)
    0x0309,  # hook above
    0x030B,  # double acute (extra-high)
    0x030C,  # caron / haček (rising)
    0x030F,  # double grave (extra-low)
    0x0311,  # inverted breve
}


def clean_ipa(text: str) -> str:
    """Strip orthographic tone/accent marks from IPA output, keeping IPA diacritics."""
    decomposed = unicodedata.normalize("NFD", text)
    kept = [c for c in decomposed if ord(c) not in _ORTHOGRAPHIC_ACCENTS]
    return unicodedata.normalize("NFC", "".join(kept))


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
