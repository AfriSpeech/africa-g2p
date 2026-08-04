"""English grapheme-to-phoneme, backed by espeak-ng.

English orthography is deep — the same letters take different values depending on
etymology and morphology, so `ough` alone has six pronunciations. The longest-match
grapheme tables that work for the shallow orthographies in this package cannot represent
that: they map ``through``, ``though``, ``tough`` and ``thought`` to one identical string.

espeak-ng carries a pronunciation lexicon plus letter-to-sound rules for anything outside
it, which matters for African names and borrowings that appear throughout African English
speech — ``Akosua``, ``Kwabena``, ``obroni`` are all handled, where a dictionary-only
approach returns nothing.

Output is normalised to the same IPA conventions as the rest of the package, so English
phonemes share one space with the 400 rule-based languages. Every symbol espeak emits
already occurs somewhere in those languages, so English introduces no foreign symbols and
no per-language tagging is needed: where a symbol is shared the sound genuinely is shared,
and where English differs IPA already distinguishes it (``æ`` is not ``a``, ``ɹ`` is not
``r``).

Requires the optional dependency::

    pip install phonemizer          # and the espeak-ng binary
"""
from __future__ import annotations

from functools import lru_cache
from typing import List

ENGLISH_CODES = {"eng", "en", "eng-us", "eng-gb"}

_VOICE = {"eng": "en-us", "en": "en-us", "eng-us": "en-us", "eng-gb": "en-gb"}

# espeak writes affricates as two bare characters; the rule tables use tie bars. Applied
# as a string replacement before the character-level normalisation below.
_AFFRICATES = (("tʃ", "t͡ʃ"), ("dʒ", "d͡ʒ"), ("ʧ", "t͡ʃ"), ("ʤ", "d͡ʒ"))

# espeak spells a few things differently from the rule tables. Only genuine
# same-sound-different-symbol cases belong here — never a real phonetic distinction.
_NORMALISE = str.maketrans({
    "g": "ɡ",       # ASCII g -> IPA script g, as norm_ipa does at build time
    "ˈ": None,      # stress marks are not phonemes
    "ˌ": None,
    "|": None,      # espeak's phrase separators
})


class EspeakUnavailable(RuntimeError):
    """Raised when phonemizer or the espeak-ng binary is missing."""


@lru_cache(maxsize=8)
def _backend(voice: str):
    try:
        from phonemizer.backend import EspeakBackend
    except ImportError as e:
        raise EspeakUnavailable(
            "English G2P needs phonemizer and espeak-ng: pip install phonemizer, "
            "and install the espeak-ng binary for your platform."
        ) from e
    try:
        return EspeakBackend(voice, with_stress=False, language_switch="remove-flags")
    except RuntimeError as e:
        raise EspeakUnavailable(f"espeak-ng could not be initialised: {e}") from e


class EnglishG2P:
    """Phonemise English text to IPA.

    Mirrors the interface of :class:`africa_g2p.G2P` so callers can treat English like any
    other language.

        >>> EnglishG2P().convert("through though tough thought")
        'θɹuː ðoʊ tʌf θɔːt'
        >>> EnglishG2P().phonemes("knight")
        ['n', 'aɪ', 't']
    """

    def __init__(self, code: str = "eng", *, output: str = "ipa") -> None:
        if output != "ipa":
            raise ValueError("English supports IPA output only; there is no rule table "
                             "to fall back on for native-orthography units")
        self.code = code
        self.output = output
        self.voice = _VOICE.get(code, "en-us")

    def convert(self, text: str, *, sep: str = "", lower: bool = True) -> str:
        return sep.join(self.phonemes(text)) if sep else self._raw(text)

    def phonemes(self, text: str, *, lower: bool = True) -> List[str]:
        """Phoneme units. Multi-character units (t͡ʃ, aɪ, oʊ, uː) are kept whole."""
        return _segment(self._raw(text))

    def _raw(self, text: str) -> str:
        if not text or not text.strip():
            return ""
        out = _backend(self.voice).phonemize([text], strip=True, njobs=1)[0]
        out = out.translate(_NORMALISE)
        for a, b in _AFFRICATES:
            out = out.replace(a, b)
        return out


# Units that must not be split into their component characters.
_MULTI = (
    "t͡ʃ", "d͡ʒ",                                     # affricates, with tie bars
    "aɪ", "aʊ", "eɪ", "oʊ", "ɔɪ", "ɪə", "eə", "ʊə",  # diphthongs
    "iː", "uː", "ɑː", "ɔː", "ɜː", "ɚ", "ɝ",           # long and r-coloured
)


def _segment(s: str) -> List[str]:
    """Longest-match segmentation, so `aɪ` is one unit rather than `a` + `ɪ`."""
    out: List[str] = []
    i = 0
    while i < len(s):
        if s[i].isspace():
            i += 1
            continue
        for m in _MULTI:
            if s.startswith(m, i):
                out.append(m)
                i += len(m)
                break
        else:
            # carry any combining marks with their base
            j = i + 1
            while j < len(s) and ord(s[j]) in range(0x300, 0x370):
                j += 1
            out.append(s[i:j])
            i = j
    return out
