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
    "ↄ": "ɔ",       # reversed c ↄ -> Latin open o ɔ (Adioukrou writes it for ɔ)
    "ɂ": "ʔ",       # Latin glottal stop ɂ -> IPA glottal stop ʔ
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


# Affricates written as two bare letters, and the precomposed ligatures, both normalised
# to the tie-bar spelling the package uses elsewhere.
#
# 126 of the 400 rule tables write `tʃ` where the rest write `t͡ʃ`, and a few carry the
# Unicode ligatures `ʧ`/`ʤ`. They are the same sounds, but a model trained on the raw
# tables sees them as different symbols: measured across the 141 AfriSpeech languages,
# `t͡ʃ` and `tʃ` appeared as separate units 134,581 and 70,142 times, splitting one
# phoneme's probability mass across two output classes for no reason.
#
# Ordered longest-first so `t͡ʃʰ` is not left half-converted by the `tʃ` rule.
_LIGATURES = {"ʧ": "t͡ʃ", "ʤ": "d͡ʒ", "ʨ": "t͡ɕ", "ʥ": "d͡ʑ", "ʦ": "t͡s", "ʣ": "d͡z"}
_AFFRICATE_PAIRS = (
    ("t", "ʃ"), ("d", "ʒ"), ("t", "ɕ"), ("d", "ʑ"), ("t", "s"), ("d", "z"),
    ("t", "ʂ"), ("d", "ʐ"), ("k", "p"), ("ɡ", "b"), ("p", "f"), ("b", "v"),
)
_TIE = "͡"


def tie_affricates(ipa: str) -> str:
    """Write affricates and doubly-articulated stops with a tie bar, consistently.

    Applied to a rule table's *values*, where the string is one grapheme's realisation, so
    an adjacent `t` and `s` there really are one affricate. It must not be run over
    converted text, where the same two symbols may be neighbouring phonemes.
    """
    for lig, rep in _LIGATURES.items():
        ipa = ipa.replace(lig, rep)
    # The marks class excludes the tie itself, so a junction that is already tied simply
    # does not match — no double ties, and no need to skip the whole value. Skipping it
    # left prenasalised segments half-done: `n͡dʒ` kept a bare `dʒ` after the first tie.
    for a, b in sorted(_AFFRICATE_PAIRS, key=lambda p: -len(p[0] + p[1])):
        pat = re.compile(re.escape(a) + "([\u0300-\u0360\u0362-\u036f]*)" + re.escape(b))
        ipa = pat.sub(lambda m: a + m.group(1) + _TIE + b, ipa)
    return ipa
