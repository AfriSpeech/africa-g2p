"""High-level pipeline API, mirroring sea-g2p's ergonomics.

    from africa_g2p import AfricaPipeline
    pipe = AfricaPipeline(lang="dyu")           # native-orthography phonemes (default)
    pipe.run("jakuma bɛ sogo dun")
    AfricaPipeline(lang="dyu", output="ipa").run("jakuma")   # IPA instead
"""
from __future__ import annotations

from typing import List, Union

from .english import ENGLISH_CODES, EnglishG2P
from .g2p import G2P
from .loader import registry


class AfricaPipeline:
    def __init__(self, lang: str, *, output: str = "grapheme",
                 unknown: str = "passthrough", strip_diacritics: bool = False):
        self.lang = lang
        # English routes to espeak, never to the rule tables. There *is* an eng.json chart, and
        # using it is silently wrong rather than merely imperfect: greedy longest-match collapses
        # through/though/tough/thought, so lang="eng" returned 'θ ɹʷ oʊ juː f' for "through" and
        # raised nothing. Wrong phonemes that look plausible are the worst failure mode a G2P has,
        # because everything downstream keeps working and only the audio is wrong.
        #
        # English has no native-orthography mode — there is no table to render units from — so the
        # "grapheme" default becomes IPA here rather than an error, since a caller iterating over
        # languages should not have to special-case one of them.
        if lang in ENGLISH_CODES:
            self.g2p = EnglishG2P(lang, output="ipa" if output == "grapheme" else output)
        else:
            self.g2p = G2P(lang, output=output, unknown=unknown,
                           strip_diacritics=strip_diacritics)
        self.info = registry().get(lang, {"code": lang})

    def run(self, text: Union[str, List[str]], *, sep: str = ""):
        """Convert text (or a batch of texts) to IPA."""
        if isinstance(text, (list, tuple)):
            return [self.g2p.convert(t, sep=sep) for t in text]
        return self.g2p.convert(text, sep=sep)

    def __repr__(self) -> str:
        name = self.info.get("name", self.lang)
        return f"AfricaPipeline(lang={self.lang!r}, name={name!r})"
