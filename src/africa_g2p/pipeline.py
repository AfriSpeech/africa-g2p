"""High-level pipeline API, mirroring sea-g2p's ergonomics.

    from africa_g2p import AfricaPipeline
    pipe = AfricaPipeline(lang="dyu")           # native-orthography phonemes (default)
    pipe.run("jakuma bɛ sogo dun")
    AfricaPipeline(lang="dyu", output="ipa").run("jakuma")   # IPA instead
"""
from __future__ import annotations

from typing import List, Union

from .g2p import G2P
from .loader import registry


class AfricaPipeline:
    def __init__(self, lang: str, *, output: str = "grapheme",
                 unknown: str = "passthrough", strip_diacritics: bool = False):
        self.lang = lang
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
