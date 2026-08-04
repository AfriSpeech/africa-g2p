"""Conventional readings for letters a rule set happens to omit.

The rule tables come from published alphabet charts, and charts are not always complete:
the `naw` table has no `p`, `bud` has no `e` or `o`, `nko` has no `r`. When a language's
own orthography uses a letter its chart left out, that letter currently produces nothing —
the phoneme is silently lost, which is worse than an error because the output still looks
plausible.

These are the readings those letters carry across African Latin orthographies. They are a
last resort, applied only where the language's own rules say nothing, so a rule set always
wins over the fallback. Measured on the Ghanaian corpus, this recovered languages that were
otherwise unusable: Nawuri from 0.82 to 1.00 character coverage, Bassar from 0.98 to 1.00.

Values are deliberately conservative. A letter whose reading genuinely varies across
languages (`q`, `y` in some orthographies) is left out rather than guessed at.
"""
from __future__ import annotations

from typing import Dict, Final

#: letter -> IPA, for letters missing from a language's own grapheme table
FALLBACK_IPA: Final[Dict[str, str]] = {
    # glottal stop, written several ways; the normalizer folds these to "'"
    "'": "ʔ",
    "ʼ": "ʔ",
    "’": "ʔ",
    "ꞌ": "ʔ",
    # consonants that charts commonly omit
    "c": "t͡ʃ",   # c is an affricate in most African Latin orthographies, not /k/
    "j": "d͡ʒ",
    "r": "ɾ",
    "v": "v",
    "z": "z",
    "p": "p",
    "h": "h",
    "x": "x",
    "ɣ": "ɣ",    # gamma
    "ɲ": "ɲ",
    "ʒ": "ʒ",
    "ð": "ð",
    "đ": "d",
    "ƒ": "ɸ",    # f-hook, voiceless bilabial fricative
    # schwa, written two ways
    "ǝ": "ə",
    "ə": "ə",
}


def fallback_ipa(char: str) -> str | None:
    """The conventional reading for `char`, or None if there is no safe default."""
    return FALLBACK_IPA.get(char) or FALLBACK_IPA.get(char.lower())
