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
    # IPA letters pressed into service as ordinary graphemes. These carry their IPA
    # value by construction — an orthography that borrows `ɛ` from the IPA does so
    # precisely to write /ɛ/ — yet most charts list them only in the rows where they
    # happen to be phonemic, so 251 of 400 tables have no entry for `ɛ` and 214 none
    # for `ŋ`. Measured on Kisi, whose donor chart omits all of ŋ, ɛ, ɔ.
    "ɛ": "ɛ",
    "ɔ": "ɔ",
    "ŋ": "ŋ",
    "ɩ": "ɪ",    # latin iota — the near-close front vowel in Gur and Kwa ATR systems
    "ʋ": "ʋ",    # v-hook, labiodental approximant (Ewe, Gbe)
    "ɓ": "ɓ",    # implosives, written with the hook letters across West Africa
    "ɗ": "ɗ",
    "ɖ": "ɖ",
    "ƙ": "kʼ",   # Hausa ejective k
    # Nigerian dot-below vowels and sibilant (Yoruba, Igbo, Edoid). No chart lists
    # them, because each language documents its own dotted letters in the base rows.
    "ẹ": "ɛ",
    "ọ": "ɔ",
    "ṣ": "ʃ",
}


def fallback_ipa(char: str) -> str | None:
    """The conventional reading for `char`, or None if there is no safe default."""
    return FALLBACK_IPA.get(char) or FALLBACK_IPA.get(char.lower())
