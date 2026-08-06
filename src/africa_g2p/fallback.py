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
    "w": "w",    # kiz omits it, and w is w wherever African Latin orthography uses it
    # Nigerian dot-below vowels and sibilant (Yoruba, Igbo, Edoid). No chart lists
    # them, because each language documents its own dotted letters in the base rows.
    "ẹ": "ɛ",
    "ọ": "ɔ",
    "ṣ": "ʃ",
    # Clicks. Khoekhoe, Nama, Damara and Juǀʼhoan write them with the IPA click letters
    # themselves, so like the borrowed vowels above these read as what they already are.
    # No Latin chart carries them, which made every click language look unphonemisable.
    "ǀ": "ǀ",    # dental
    "ǁ": "ǁ",    # lateral
    "ǃ": "ǃ",    # alveolar
    "ǂ": "ǂ",    # palatal
    "ʘ": "ʘ",    # bilabial
}

#: Spacing modifier letters used as orthographic tone marks.
#:
#: The Kru orthographies of Côte d'Ivoire — Dida, Godié, Bété, Attié — mark tone with a
#: raised bar written *beside* the syllable rather than as a combining mark on the vowel.
#: Because they are spacing characters they never attach to a base letter, so segmentation
#: treated each one as an unknown grapheme: tone notation alone put Attié at 0.86 and Dida
#: at 0.85, low enough to look like languages that could not be phonemised at all.
#:
#: They carry tone, not a segment, so they are dropped from IPA output rather than guessed
#: at — which bar means which tone is language-specific and no chart records it. A language
#: that *does* define one in its diacritics table still wins, as everywhere else.
SPACING_TONE: Final[frozenset] = frozenset("ˈˉˊˋˌ˗˖")


def fallback_ipa(char: str) -> str | None:
    """The conventional reading for `char`, or None if there is no safe default."""
    return FALLBACK_IPA.get(char) or FALLBACK_IPA.get(char.lower())
