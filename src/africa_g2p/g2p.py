"""Core grapheme-to-phoneme engine.

The algorithm is greedy longest-match multigraph segmentation over a per-language
grapheme table, with trailing combining marks (tone, nasalization, length) mapped
separately as suprasegmentals. This suits the shallow, largely phonemic orthographies
documented in Hartell's *Alphabets of Africa* (UNESCO, 1993).
"""
from __future__ import annotations

import unicodedata
from typing import Dict, List, Optional

from .loader import load_rules
from .normalizer import fold_confusables, normalize_text, tokenize


class G2P:
    """Grapheme-to-phoneme converter for a single language."""

    def __init__(self, code: str, *, unknown: str = "passthrough"):
        """
        Args:
            code: ISO 639-3 language code with a rule file.
            unknown: how to treat a grapheme with no mapping —
                     "passthrough" (keep the character), "drop", or "mark" (�).
        """
        self.code = code
        self.rules = load_rules(code)
        self.unknown = unknown

        # Grapheme table: base letters (no combining marks) -> IPA string.
        # Grapheme keys are lowercased + confusable-folded to match normalized input.
        self.graphemes: Dict[str, str] = {
            unicodedata.normalize("NFD", fold_confusables(g.lower())): ipa
            for g, ipa in self.rules["graphemes"].items()
        }
        self._max_len = max((len(g) for g in self.graphemes), default=1)

        # Diacritic table: combining codepoint -> IPA suprasegmental suffix.
        self.diacritics: Dict[str, str] = dict(self.rules.get("diacritics", {}))

    # ------------------------------------------------------------------ public
    def convert(self, text: str, *, sep: str = "", lower: bool = True) -> str:
        """Convert a full text string to an IPA string."""
        text = normalize_text(text, lower=lower)
        out: List[str] = []
        for tok in tokenize(text):
            if tok.is_word:
                out.append(self._convert_word(tok.text, sep=sep))
            else:
                out.append(tok.text)
        return "".join(out)

    def convert_word(self, word: str, *, sep: str = "", lower: bool = True) -> str:
        """Convert a single word (no tokenization) to IPA."""
        word = normalize_text(word, lower=lower)
        return self._convert_word(word, sep=sep)

    def phonemes(self, text: str, *, lower: bool = True) -> List[str]:
        """Return a flat list of phoneme units for the text (words only)."""
        text = normalize_text(text, lower=lower)
        units: List[str] = []
        for tok in tokenize(text):
            if tok.is_word:
                units.extend(self._segment(tok.text))
        return units

    # ----------------------------------------------------------------- private
    def _convert_word(self, word: str, *, sep: str) -> str:
        return sep.join(self._segment(word))

    def _segment(self, word: str) -> List[str]:
        """Segment one word into a list of IPA units."""
        text = unicodedata.normalize("NFD", word)
        n = len(text)
        i = 0
        units: List[str] = []
        while i < n:
            match = self._longest_base_match(text, i, n)
            if match is None:
                ch = text[i]
                if unicodedata.combining(ch):
                    # stray combining mark with no base — attach or drop silently
                    i += 1
                    continue
                units.append(self._handle_unknown(ch))
                i += 1
                continue
            base_ipa, length = match
            i += length
            # collect trailing combining marks (tone / nasal / length)
            suffix = ""
            while i < n and unicodedata.combining(text[i]):
                suffix += self.diacritics.get(text[i], "")
                i += 1
            units.append(base_ipa + suffix)
        return units

    def _longest_base_match(self, text: str, i: int, n: int):
        upper = min(self._max_len, n - i)
        for length in range(upper, 0, -1):
            chunk = text[i:i + length]
            if any(unicodedata.combining(c) for c in chunk):
                continue
            ipa = self.graphemes.get(chunk)
            if ipa is not None:
                return ipa, length
        return None

    def _handle_unknown(self, ch: str) -> str:
        if self.unknown == "drop":
            return ""
        if self.unknown == "mark":
            return "�"
        return ch


def g2p(text: str, lang: str, **kwargs) -> str:
    """One-shot convenience wrapper: ``g2p("akwaaba", "aka")``."""
    return G2P(lang).convert(text, **kwargs)
